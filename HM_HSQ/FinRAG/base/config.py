import configparser
import hashlib
import os
from pathlib import Path

class Config:
    def __init__(self, config_file=None, knowledge_base=None):
        path = Path(config_file or Path(__file__).resolve().parents[1] / 'config.ini').resolve()
        parser = configparser.ConfigParser(interpolation=None)
        if not parser.read(path, encoding='utf-8-sig'):
            raise FileNotFoundError(path)
        self.KNOWLEDGE_BASE = knowledge_base or parser.get('rag', 'knowledge_base')
        if not self.KNOWLEDGE_BASE.strip():
            raise ValueError('knowledge_base must not be empty')
        self.MILVUS_COLLECTION_NAME = 'rag_' + hashlib.sha256(self.KNOWLEDGE_BASE.encode()).hexdigest()
        self.DOMAIN = parser.get('rag', 'domain', fallback='通用')
        self.INSTRUCTIONS = parser.get('rag', 'instructions', fallback='')
        self.MILVUS_HOST = parser.get('milvus', 'host')
        self.MILVUS_PORT = parser.get('milvus', 'port')
        self.MILVUS_DATABASE_NAME = parser.get('milvus', 'database_name')
        self.LLM_MODEL = parser.get('llm', 'model')
        self.DASHSCOPE_API_KEY = os.getenv('RAG_API_KEY') or os.getenv('DASHSCOPE_API_KEY') or parser.get('llm', 'api_key', fallback='')
        self.DASHSCOPE_BASE_URL = os.getenv('RAG_BASE_URL') or parser.get('llm', 'base_url')
        self.M3_MODEL_PATH = str((path.parent / parser.get('models', 'embedding')).resolve())
        self.RERANK_MODEL_PATH = str((path.parent / parser.get('models', 'reranker')).resolve())
        for name, default in [('parent_chunk_size', 1200), ('child_chunk_size', 300), ('chunk_overlap', 50), ('retrieval_k', 10), ('candidate_m', 3)]:
            setattr(self, name.upper(), parser.getint('retrieval', name, fallback=default))
        if not 0 <= self.CHUNK_OVERLAP < self.CHILD_CHUNK_SIZE <= self.PARENT_CHUNK_SIZE <= 8000:
            raise ValueError('Require 0 <= overlap < child <= parent <= 8000')
        if not 0 < self.CANDIDATE_M <= self.RETRIEVAL_K:
            raise ValueError('Require 0 < candidate_m <= retrieval_k')
