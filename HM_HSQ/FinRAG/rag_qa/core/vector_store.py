import torch
from milvus_model.hybrid import BGEM3EmbeddingFunction
from pymilvus import MilvusClient, DataType, AnnSearchRequest, WeightedRanker
from langchain_core.documents import Document
from sentence_transformers import CrossEncoder
import hashlib
import json

from base import logger, Config

class VectorStore:
    def __init__(self, config=None, shared_models=None):
        conf = config or Config()
        self.config = conf
        self.collection_name = conf.MILVUS_COLLECTION_NAME
        self.host = conf.MILVUS_HOST
        self.port = conf.MILVUS_PORT
        self.database = conf.MILVUS_DATABASE_NAME
        self.logger = logger

        self.device = 'cuda' if torch.cuda.is_available() else 'cpu'

        self.logger.info(f"使用设备：{self.device}")

        if shared_models is None:
            self.reranker = CrossEncoder(conf.RERANK_MODEL_PATH, device=self.device)
            self.embedding_function = BGEM3EmbeddingFunction(
                model_name_or_path=conf.M3_MODEL_PATH, use_fp16=False, device="cpu")
        else:
            self.embedding_function, self.reranker = shared_models

        self.dense_dim = self.embedding_function.dim["dense"]
        self.client = MilvusClient(uri=f"http://{self.host}:{self.port}",
                                   db_name=self.database)
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

    def add_documents(self, documents):
        for start in range(0, len(documents), 32):
            self._add_batch(documents[start:start + 32])
        self.client.flush(collection_name=self.collection_name)

    def _add_batch(self, documents):

        texts = [doc.page_content for doc in documents]
        embeddings = self.embedding_function(texts)
        data = []
        for i, doc in enumerate(documents):
            text_hash = hashlib.sha256(json.dumps([doc.metadata, doc.page_content], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
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
                "timestamp": doc.metadata.get("timestamp", "unknown")
            })
        if data:
            self.client.upsert(collection_name=self.collection_name, data=data)
            logger.info(f"已插入或更新 {len(data)} 个文档")

    def hybrid_search_with_rerank(self, query, k=None, source_filter=None):
        k = k or self.config.RETRIEVAL_K

        query_embeddings = self.embedding_function([query])

        dense_query_vector = query_embeddings["dense"][0]

        sparse_query_vector = {}
        row = query_embeddings["sparse"][[0], :].tocsr()

        indices = row.indices

        values = row.data

        for idx, value in zip(indices, values):
            sparse_query_vector[int(idx)] = float(value)

        filter_expr = 'source == ' + json.dumps(source_filter, ensure_ascii=False) if source_filter else ""
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
            consistency_level="Strong", output_fields=["text", "parent_id", "parent_content", "source", "page", "timestamp"]
        )[0]

        sub_chunks = [self._doc_from_hit(hit["entity"]) for hit in results]
        parent_docs = self._get_unique_parent_docs(sub_chunks)
        if len(parent_docs) < 2:
            return parent_docs[:self.config.CANDIDATE_M]
        if parent_docs:
            pairs = [[query, doc.page_content] for doc in parent_docs]
            scores = self.reranker.predict(pairs)
            ranked_parent_docs = [doc for _, doc in sorted(zip(scores, parent_docs), key=lambda pair: float(pair[0]), reverse=True)]
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
        return Document(
            page_content=hit.get("text"),
            metadata={
                "parent_id": hit.get("parent_id"),
                "parent_content": hit.get("parent_content"),
                "source": hit.get("source"),
                "page": hit.get("page", 1),
                "timestamp": hit.get("timestamp")
            }
        )

    def close(self):
        self.client.close()
