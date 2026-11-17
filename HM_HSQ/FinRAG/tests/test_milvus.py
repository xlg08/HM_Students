"""Opt-in real Milvus integration with deterministic models, isolated temporary collections."""
import os
import json
import tempfile
import uuid
import unittest
from pathlib import Path


def make_store(name, directory):
    import numpy as np
    from scipy.sparse import csr_matrix
    from pymilvus import MilvusClient
    from filelock import FileLock
    from base import Config, logger
    from rag_qa.core.vector_store import VectorStore
    class Embedding:
        def __call__(self, texts):
            vectors = [[1., 0., 0., 0., 0., 0., 0., 0.] if 'ALPHA' in text else [0., 1., 0., 0., 0., 0., 0., 0.] for text in texts]
            dense = np.asarray(vectors, dtype='float32')
            return {'dense': dense, 'sparse': csr_matrix(dense)}
    class Reranker:
        def predict(self, pairs, **kwargs):
            return [1. for _ in pairs]
    store = VectorStore.__new__(VectorStore)
    store.config = Config(knowledge_base=name)
    store.collection_name = store.config.MILVUS_COLLECTION_NAME
    store.client = MilvusClient('http://localhost:19530')
    store.embedding_function = Embedding()
    store.reranker = Reranker()
    store.dense_dim = 8
    store.logger = logger
    store.manifest_path = Path(directory) / (store.collection_name + '.json')
    store.index_lock = FileLock(str(store.manifest_path) + '.lock')
    store._create_or_load_collection()
    return store


@unittest.skipUnless(os.getenv('RAG_INTEGRATION') == '1', 'Set RAG_INTEGRATION=1 for real Milvus')
class IsolationTests(unittest.TestCase):
    def test_pdf_directory_ingestion_and_unknown_collection(self):
        from new_main import IntegratedQASystem
        from base import Config
        from rag_qa.core.vector_store import VectorStore
        try:
            import pymupdf as fitz
        except ImportError:
            import fitz
        with self.assertRaises(KeyError):
            VectorStore(Config(knowledge_base='missing_' + uuid.uuid4().hex), create=False)
        with tempfile.TemporaryDirectory() as temporary:
            store = make_store('verify_' + uuid.uuid4().hex, temporary)
            try:
                directory = Path(temporary) / 'documents'
                directory.mkdir()
                path = directory / 'alpha.pdf'
                with fitz.open() as pdf:
                    page = pdf.new_page()
                    page.insert_text((60, 60), 'ALPHA PDF ingestion marker')
                    pdf.save(path)
                (directory / 'notes.txt').write_text('BETA directory marker')
                application = IntegratedQASystem(store.config, vector_store=store, llm=lambda prompt: 'test answer')
                self.assertGreater(application.ingest(path), 0)
                self.assertGreater(application.ingest(directory), 1)
                result = application.rag_system.answer('ALPHA')
                self.assertTrue(result['sources'])
                self.assertEqual(result['collection'], store.config.KNOWLEDGE_BASE)
            finally:
                store.client.drop_collection(store.collection_name)
                store.close()

    def test_isolation_updates_retry_delete_and_reload(self):
        from rag_qa.core.document_processor import process_documents
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as temporary:
            stores = []
            try:
                for marker in ['ALPHA', 'BETA', 'GAMMA']:
                    store = make_store('verify_' + uuid.uuid4().hex, temporary)
                    stores.append(store)
                    path = Path(temporary) / (marker + '.txt')
                    path.write_text(marker + ' unique original content')
                    docs = process_documents(path)
                    store.add_documents(docs)
                    store.add_documents(docs)
                    result = store.hybrid_search_with_rerank(marker)
                    self.assertTrue(result)
                    self.assertTrue(all(marker in doc.page_content for doc in result))
                    self.assertTrue(all(doc.metadata['source'] == str(path) for doc in result))
                    self.assertEqual(len(store.client.query(store.collection_name, filter='', output_fields=['id'], limit=100, consistency_level='Strong')), 1)
                store = stores[0]
                path = Path(temporary) / 'ALPHA.txt'
                self.assertEqual(store.resolve_document_source(path.name, '/fallback'), str(path))
                with patch.object(store.reranker, 'predict', return_value=[float('nan')]):
                    fallback = store.hybrid_search_with_rerank('ALPHA')
                    self.assertTrue(fallback[0].metadata['retrieval_warning'])
                path.write_text('ALPHA replacement content')
                store.add_documents(process_documents(path))
                self.assertNotIn('original', store.hybrid_search_with_rerank('ALPHA')[0].page_content)
                path.write_text('ALPHA incomplete update')
                with patch.object(store, '_add_batch', side_effect=RuntimeError('interrupted')):
                    with self.assertRaises(RuntimeError):
                        store.add_documents(process_documents(path))
                self.assertIn('replacement', store.hybrid_search_with_rerank('ALPHA')[0].page_content)
                import subprocess
                import sys
                code = "import sys; u=[p for p in sys.path if 'AppData' in p and 'site-packages' in p]; sys.path[:]=[p for p in sys.path if p not in u]+u; sys.path.insert(0,'tests'); from test_milvus import make_store; s=make_store(sys.argv[1],sys.argv[2]); assert 'replacement' in s.hybrid_search_with_rerank('ALPHA')[0].page_content; s.close(); print('reload OK')"
                child = subprocess.run([sys.executable, '-X', 'utf8', '-c', code, store.config.KNOWLEDGE_BASE, temporary], capture_output=True, text=True, timeout=120)
                self.assertEqual(child.returncode, 0, child.stderr)
                reloaded = make_store(store.config.KNOWLEDGE_BASE, temporary)
                self.assertIn('replacement', reloaded.hybrid_search_with_rerank('ALPHA')[0].page_content)
                reloaded.close()
                self.assertEqual(store.delete_document(str(path)), 1)
                self.assertEqual(store.hybrid_search_with_rerank('ALPHA'), [])
            finally:
                for store in stores:
                    store.client.drop_collection(store.collection_name)
                    store.close()
