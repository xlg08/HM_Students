import torch
from milvus_model.hybrid import BGEM3EmbeddingFunction
from pymilvus import MilvusClient, DataType, AnnSearchRequest, WeightedRanker
from langchain_core.documents import Document
from sentence_transformers import CrossEncoder
import hashlib
import json
import math
from pathlib import Path
from collections import defaultdict
from filelock import FileLock

from base import logger, Config

class VectorStore:
    def __init__(self, config=None, shared_models=None, create=True):
        conf = config or Config()
        self.config = conf
        self.collection_name = conf.MILVUS_COLLECTION_NAME
        self.host = conf.MILVUS_HOST
        self.port = conf.MILVUS_PORT
        self.database = conf.MILVUS_DATABASE_NAME
        self.logger = logger

        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'

        self.logger.info(f"使用设备：{self.device}")

        self.client = MilvusClient(uri=f"http://{self.host}:{self.port}", db_name=self.database)
        if not create and not self.client.has_collection(self.collection_name):
            self.client.close()
            raise KeyError(f'Collection does not exist: {conf.KNOWLEDGE_BASE}')
        index_directory = Path(__file__).resolve().parents[2] / '.runtime' / 'indexes'
        index_directory.mkdir(parents=True, exist_ok=True)
        self.manifest_path = index_directory / (self.collection_name + '.json')
        self.index_lock = FileLock(str(self.manifest_path) + '.lock', timeout=180)
        if shared_models is None:
            self.reranker = CrossEncoder(conf.RERANK_MODEL_PATH, device=self.device)
            self.reranker.model.float()
            self.embedding_function = BGEM3EmbeddingFunction(
                model_name_or_path=conf.M3_MODEL_PATH, use_fp16=False, device="cpu")
        else:
            self.embedding_function, self.reranker = shared_models

        self.dense_dim = self.embedding_function.dim["dense"]
        self._create_or_load_collection()

    def _create_or_load_collection(self):
        if not self.client.has_collection(self.collection_name):

            schema = self.client.create_schema(auto_id=False, enable_dynamic_field=True)

            schema.add_field(field_name="id", datatype=DataType.VARCHAR, is_primary=True, max_length=100)
            schema.add_field(field_name="text", datatype=DataType.VARCHAR, max_length=65535)
            schema.add_field(field_name="dense_vector", datatype=DataType.FLOAT_VECTOR, dim=self.dense_dim)
            schema.add_field(field_name="sparse_vector", datatype=DataType.SPARSE_FLOAT_VECTOR)
            schema.add_field(field_name="parent_id", datatype=DataType.VARCHAR, max_length=100)
            schema.add_field(field_name="parent_content", datatype=DataType.VARCHAR, max_length=65535)
            schema.add_field(field_name="source", datatype=DataType.VARCHAR, max_length=4096)
            schema.add_field(field_name="page", datatype=DataType.INT64)
            schema.add_field(field_name="timestamp", datatype=DataType.VARCHAR, max_length=50)

            index_params = self.client.prepare_index_params()
            index_params.add_index(
                field_name="dense_vector",
                index_name="dense_index",
                index_type="IVF_FLAT",
                metric_type="IP",
                params={"nlist": 128}
            )
            index_params.add_index(
                field_name="sparse_vector",
                index_name="sparse_index",
                index_type="SPARSE_INVERTED_INDEX",
                metric_type="IP",
                params={"drop_ratio_build": 0.2}
            )

            self.client.create_collection(collection_name=self.collection_name, schema=schema,
                                         index_params=index_params)
            logger.info(f"已创建集合 {self.collection_name}")
        else:
            logger.info(f"已加载集合 {self.collection_name}")
        self.client.load_collection(self.collection_name)

    def _manifest(self):
        if self.manifest_path.exists():
            manifest = json.loads(self.manifest_path.read_text(encoding='utf-8'))
            if manifest.get('embedding_model', self.config.M3_MODEL_PATH) != self.config.M3_MODEL_PATH:
                raise ValueError('Embedding model changed; use a new collection and rebuild the index')
            return manifest
        sources = defaultdict(list)
        iterator = self.client.query_iterator(collection_name=self.collection_name, batch_size=1000,
            filter='', output_fields=['id', 'source'], consistency_level='Strong')
        try:
            while True:
                rows = iterator.next()
                if not rows:
                    break
                for row in rows:
                    sources[row['source']].append(row['id'])
        finally:
            iterator.close()
        manifest = {'sources': dict(sources), 'embedding_model': self.config.M3_MODEL_PATH}
        self._save_manifest(manifest)
        return manifest

    def _save_manifest(self, manifest):
        if self.manifest_path.exists():
            self.manifest_path.with_suffix('.previous.json').write_bytes(self.manifest_path.read_bytes())
        temporary = self.manifest_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(manifest, ensure_ascii=False), encoding='utf-8')
        temporary.replace(self.manifest_path)

    def add_documents(self, documents):
        if not documents:
            raise ValueError('No chunks to index')
        grouped = defaultdict(list)
        for doc in documents:
            grouped[doc.metadata['source']].append(doc)
        with self.index_lock:
            manifest = self._manifest()
            for source, chunks in grouped.items():
                new_ids = {doc.metadata['chunk_id'] for doc in chunks}
                for start in range(0, len(chunks), 32):
                    self._add_batch(chunks[start:start + 32])
                self.client.flush(collection_name=self.collection_name)
                manifest['sources'][source] = sorted(new_ids)
                self._save_manifest(manifest)
                # Old versions stay physically available for manifest rollback; search only uses active IDs.

    def resolve_document_source(self, document_name, default_source):
        with self.index_lock:
            manifest = self._manifest()
            matches = [source for source in manifest['sources'] if Path(source).name == document_name]
            if len(matches) > 1:
                raise ValueError('Multiple source paths use this filename; manage them through CLI first')
            return matches[0] if matches else default_source

    def delete_document(self, source):
        with self.index_lock:
            manifest = self._manifest()
            ids = manifest['sources'].pop(source, [])
            self._save_manifest(manifest)
            return len(ids)

    def _add_batch(self, documents):

        texts = [doc.page_content for doc in documents]
        embeddings = self.embedding_function(texts)
        data = []
        for i, doc in enumerate(documents):
            text_hash = doc.metadata['chunk_id']
            sparse_vector = {}

            row = embeddings["sparse"][[i], :].tocsr()

            indices = row.indices

            values = row.data
            for idx, value in zip(indices, values):
                sparse_vector[int(idx)] = float(value)
            data.append({
                "id": text_hash,
                "text": doc.page_content,
                "dense_vector": embeddings["dense"][i],
                "sparse_vector": sparse_vector,
                "parent_id": doc.metadata["parent_id"],
                "parent_content": doc.metadata["parent_content"],
                "source": doc.metadata["source"],
                "page": doc.metadata["page"],
                "timestamp": doc.metadata.get("timestamp", "unknown"),
                "metadata": doc.metadata
            })
        if data:
            self.client.upsert(collection_name=self.collection_name, data=data)
            logger.info(f"已插入或更新 {len(data)} 个文档")

    def hybrid_search_with_rerank(self, query, k=None, source_filter=None):
        with self.index_lock:
            return self._search(query, k, source_filter)

    def _search(self, query, k=None, source_filter=None):
        k = k or self.config.RETRIEVAL_K

        active_filter = ''
        if self.manifest_path.exists():
            manifest = self._manifest()
            ids = [identity for group in manifest['sources'].values() for identity in group]
            if not ids:
                return []
            active_filter = 'id in ' + json.dumps(ids)
        query_embeddings = self.embedding_function([query])

        dense_query_vector = query_embeddings["dense"][0]

        sparse_query_vector = {}
        row = query_embeddings["sparse"][[0], :].tocsr()

        indices = row.indices

        values = row.data

        for idx, value in zip(indices, values):
            sparse_query_vector[int(idx)] = float(value)

        filter_expr = 'source == ' + json.dumps(source_filter, ensure_ascii=False) if source_filter else ""
        if active_filter:
            filter_expr = f'({filter_expr}) and ({active_filter})' if filter_expr else active_filter
        dense_request = AnnSearchRequest(
            data=[dense_query_vector],
            anns_field="dense_vector",
            param={"metric_type": "IP", "params": {"nprobe": 10}},
            limit=k,
            expr=filter_expr
        )
        sparse_request = AnnSearchRequest(
            data=[sparse_query_vector],
            anns_field="sparse_vector",
            param={"metric_type": "IP", "params": {}},
            limit=k,
            expr=filter_expr
        )

        ranker = WeightedRanker(1, 0.7)
        results = self.client.hybrid_search(
            collection_name=self.collection_name,
            reqs=[dense_request, sparse_request],
            ranker=ranker,
            limit=k,
            consistency_level="Strong", output_fields=["text", "parent_id", "parent_content", "source", "page", "timestamp", "metadata"]
        )[0]

        sub_chunks = [self._doc_from_hit(hit["entity"]) for hit in results]
        parent_docs = self._get_unique_parent_docs(sub_chunks)
        if parent_docs:
            pairs = [[query, doc.page_content] for doc in parent_docs]
            scores = self.reranker.predict(pairs, batch_size=1)
            if not all(math.isfinite(float(score)) for score in scores):
                logger.warning('Reranker returned non-finite scores; using hybrid retrieval ranking')
                for doc in parent_docs:
                    doc.metadata['retrieval_warning'] = '重排序模型数值异常，本次使用混合检索原始排序。'
                ranked_parent_docs = parent_docs
            else:
                ranked_parent_docs = []
                for score, doc in sorted(zip(scores, parent_docs), key=lambda pair: float(pair[0]), reverse=True):
                    doc.metadata['rerank_score'] = float(score)
                    if float(score) >= self.config.MIN_RERANK_SCORE:
                        ranked_parent_docs.append(doc)
        else:
            ranked_parent_docs = []

        return ranked_parent_docs[:self.config.CANDIDATE_M]

    def _get_unique_parent_docs(self, sub_chunks):

        parent_contents = set()

        unique_docs = []
        for chunk in sub_chunks:
            parent_content = chunk.metadata.get("parent_content", chunk.page_content)
            identity = chunk.metadata["parent_id"]
            if parent_content and identity not in parent_contents:
                unique_docs.append(Document(page_content=parent_content, metadata=chunk.metadata))
                parent_contents.add(identity)
        return unique_docs

    def _doc_from_hit(self, hit):
        metadata = hit.get('metadata') or {}
        return Document(
            page_content=hit.get("text"),
            metadata={
                **metadata,
                "chunk_id": metadata.get("chunk_id", hit.get("parent_id")),
                "document": metadata.get("document", Path(hit.get("source", "unknown")).name),
                "parent_id": hit.get("parent_id"),
                "parent_content": hit.get("parent_content"),
                "source": hit.get("source"),
                "page": hit.get("page", 1),
                "timestamp": hit.get("timestamp")
            }
        )

    def close(self):
        self.client.close()
