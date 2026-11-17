import configparser
import hashlib
import os
import re
from pathlib import Path

class Config:
    def __init__(self, config_file=None, knowledge_base=None):
        path = Path(config_file or Path(__file__).resolve().parents[1] / 'config.ini').resolve()
        parser = configparser.ConfigParser(interpolation=None)
        if not parser.read(path, encoding='utf-8-sig'):
            raise FileNotFoundError(path)
        self.KNOWLEDGE_BASE = knowledge_base or os.getenv('RAG_COLLECTION') or parser.get('rag', 'knowledge_base')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', self.KNOWLEDGE_BASE):
            raise ValueError('knowledge_base must not be empty')
        overlay = path.parent / 'configs' / 'collections' / (self.KNOWLEDGE_BASE + '.ini')
        if overlay.exists():
            parser.read(overlay, encoding='utf-8-sig')
        self.MILVUS_COLLECTION_NAME = 'rag_' + hashlib.sha256(self.KNOWLEDGE_BASE.encode()).hexdigest()
        self.DOMAIN = parser.get('rag', 'domain', fallback='通用')
        self.INSTRUCTIONS = parser.get('rag', 'instructions', fallback='')
        self.MILVUS_HOST = parser.get('milvus', 'host')
        self.MILVUS_PORT = parser.get('milvus', 'port')
        self.MILVUS_DATABASE_NAME = parser.get('milvus', 'database_name')
        self.LLM_MODEL = os.getenv('RAG_LLM_MODEL') or parser.get('llm', 'model')
        self.DASHSCOPE_API_KEY = os.getenv('RAG_API_KEY') or os.getenv('DASHSCOPE_API_KEY') or parser.get('llm', 'api_key', fallback='')
        self.DASHSCOPE_BASE_URL = os.getenv('RAG_BASE_URL') or parser.get('llm', 'base_url')
        self.M3_MODEL_PATH = str((path.parent / parser.get('models', 'embedding')).resolve())
        self.RERANK_MODEL_PATH = str((path.parent / parser.get('models', 'reranker')).resolve())
        for name, default in [('parent_chunk_size', 1200), ('child_chunk_size', 300), ('chunk_overlap', 50), ('retrieval_k', 10), ('candidate_m', 3)]:
            setattr(self, name.upper(), int(os.getenv('RAG_' + name.upper(), parser.getint('retrieval', name, fallback=default))))
        if not 0 <= self.CHUNK_OVERLAP < self.CHILD_CHUNK_SIZE <= self.PARENT_CHUNK_SIZE <= 8000:
            raise ValueError('Require 0 <= overlap < child <= parent <= 8000')
        if not 0 < self.CANDIDATE_M <= self.RETRIEVAL_K:
            raise ValueError('Require 0 < candidate_m <= retrieval_k')

        self.MAX_CONTEXT_TOKENS = parser.getint('retrieval', 'max_context_tokens', fallback=3000)
        self.MIN_RERANK_SCORE = parser.getfloat('retrieval', 'min_rerank_score', fallback=-100.0)
        self.DOCUMENT_DIRECTORY = str((path.parent / parser.get('rag', 'document_directory', fallback='documents')).resolve())
        if not 128 <= self.MAX_CONTEXT_TOKENS <= 16000:
            raise ValueError('max_context_tokens must be between 128 and 16000')
