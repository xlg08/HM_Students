"""FastAPI adapter for the document RAG engine."""
import json
import logging
import os
import threading
import uuid
import hashlib
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from base import Config
from new_main import IntegratedQASystem

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / '.runtime' / 'web'
DATA.mkdir(parents=True, exist_ok=True)
REGISTRY = DATA / 'knowledge_bases.json'
lock = threading.Lock()
systems = {}
shared_models = {}
logger = logging.getLogger(__name__)


def read_registry():
    if REGISTRY.exists():
        return json.loads(REGISTRY.read_text(encoding='utf-8'))
    return {'finance': {'id': 'finance', 'name': '金融知识库', 'domain': '金融', 'instructions': '', 'documents': []}}


def save_registry(registry):
    temporary = REGISTRY.with_suffix('.tmp')
    temporary.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(REGISTRY)


def find_base(base_id):
    entry = read_registry().get(base_id)
    if entry is None:
        raise HTTPException(404, '知识库不存在')
    return entry


def get_system(base_id):
    entry = find_base(base_id)
    if base_id not in systems:
        from rag_qa.core.vector_store import VectorStore
        config = Config(knowledge_base=base_id)
        config.DOMAIN = entry['domain']
        config.INSTRUCTIONS = entry['instructions'] or config.INSTRUCTIONS
        model_key = (config.M3_MODEL_PATH, config.RERANK_MODEL_PATH)
        store = VectorStore(config, shared_models=shared_models.get(model_key))
        shared_models[model_key] = (store.embedding_function, store.reranker)
        systems[base_id] = IntegratedQASystem(config, vector_store=store)
    return systems[base_id]


@asynccontextmanager
async def lifespan(app):
    config = Config()
    hostname = urlsplit(config.DASHSCOPE_BASE_URL).hostname
    previous = os.environ.get('NO_PROXY') or os.environ.get('no_proxy', '')
    os.environ['NO_PROXY'] = ','.join(filter(None, [previous, hostname, 'localhost', '127.0.0.1']))
    yield
    for system in systems.values():
        system.close()


app = FastAPI(title='通用 RAG API', version='1.0.0', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:5173', 'http://127.0.0.1:5173'],
                   allow_methods=['GET', 'POST', 'DELETE'], allow_headers=['Content-Type'])


class BaseCreate(BaseModel):
    id: str = Field(pattern=r'^[a-zA-Z0-9_-]{1,64}$')
    name: str = Field(min_length=1, max_length=80)
    domain: str = Field(min_length=1, max_length=80)
    instructions: str = Field(default='', max_length=2000)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    session_id: uuid.UUID


@app.get('/api/health')
def health():
    return {'status': 'ok', 'model_loaded': bool(shared_models)}


@app.get('/api/knowledge-bases')
def list_bases():
    with lock:
        return list(read_registry().values())


@app.post('/api/knowledge-bases', status_code=201)
def create_base(body: BaseCreate):
    with lock:
        registry = read_registry()
        if body.id in registry:
            raise HTTPException(409, '知识库标识已存在')
        entry = body.model_dump()
        entry['documents'] = []
        registry[body.id] = entry
        save_registry(registry)
        return entry


@app.get('/api/knowledge-bases/{base_id}/documents')
def list_documents(base_id: str):
    with lock:
        return find_base(base_id)['documents']


@app.post('/api/knowledge-bases/{base_id}/documents', status_code=201)
def upload_document(base_id: str, file: UploadFile = File(...)):
    from rag_qa.core.document_processor import SUPPORTED_EXTENSIONS
    name = (file.filename or '').replace('\\', '/').split('/')[-1]
    suffix = Path(name).suffix.lower()
    if suffix not in SUPPORTED_EXTENSIONS:
        raise HTTPException(415, '不支持该文件格式')
    with lock:
        find_base(base_id)
        directory = DATA / 'uploads' / base_id
        directory.mkdir(parents=True, exist_ok=True)
        temporary = directory / (uuid.uuid4().hex + '.part')
        size = 0
        digest = hashlib.sha256()
        try:
            with temporary.open('wb') as target:
                while chunk := file.file.read(1024 * 1024):
                    size += len(chunk)
                    if size > 50 * 1024 * 1024:
                        raise HTTPException(413, '文件大小上限为 50 MB')
                    digest.update(chunk)
                    target.write(chunk)
            if size == 0:
                raise HTTPException(400, '文件为空')
            path = directory / (digest.hexdigest() + suffix)
            temporary.replace(path)
            system = get_system(base_id)
            logical_source = system.vector_store.resolve_document_source(name, str(directory / name))
            chunks = system.ingest(path, source=logical_source, document_name=name)
            registry = read_registry()
            record = {'id': hashlib.sha256(name.encode()).hexdigest(), 'name': name, 'size': size, 'chunks': chunks, 'source': logical_source}
            documents = registry[base_id]['documents']
            registry[base_id]['documents'] = [doc for doc in documents if doc['name'] != name] + [record]
            save_registry(registry)
            return record
        except HTTPException:
            raise
        except (ValueError, FileNotFoundError) as error:
            raise HTTPException(422, str(error))
        except Exception:
            logger.exception('Document ingestion failed')
            raise HTTPException(500, '文档入库失败，请检查后端日志并重试')
        finally:
            temporary.unlink(missing_ok=True)
            file.file.close()


def event(kind, data):
    return f'event: {kind}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n'


@app.post('/api/knowledge-bases/{base_id}/chat')
def chat(base_id: str, body: ChatRequest):
    find_base(base_id)
    if not body.question.strip():
        raise HTTPException(422, '问题不能为空')

    def stream():
        # One inference at a time protects shared CPU models and session updates.
        with lock:
            try:
                system = get_system(base_id)
                for token, complete in system.query(body.question, session_id=str(body.session_id)):
                    if token:
                        yield event('token', {'content': token})
                    if complete:
                        yield event('done', {'session_id': str(body.session_id)})
            except Exception:
                logger.exception('Question generation failed')
                yield event('error', {'message': '问答失败，请检查模型配置、网络连接和后端日志'})
    return StreamingResponse(stream(), media_type='text/event-stream',
                             headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@app.delete('/api/knowledge-bases/{base_id}/sessions/{session_id}')
def clear_session(base_id: str, session_id: uuid.UUID):
    with lock:
        find_base(base_id)
        if base_id in systems:
            systems[base_id].clear_session_history(str(session_id))
    return {'success': True}


class QueryRequest(BaseModel):
    collection: str = Field(pattern=r'^[A-Za-z0-9_-]{1,64}$')
    question: str = Field(min_length=1, max_length=4000)
    top_k: int | None = Field(default=None, ge=1, le=100)


@app.post('/api/v1/rag/query')
def query_result(body: QueryRequest):
    with lock:
        find_base(body.collection)
        try:
            return get_system(body.collection).rag_system.answer(body.question, body.top_k)
        except ValueError as error:
            raise HTTPException(422, str(error))
        except Exception:
            logger.exception('Query failed')
            raise HTTPException(502, 'Model or retrieval service failed; check backend logs')


@app.post('/api/v1/documents/ingest', status_code=201)
def ingest_uploaded(collection: str, file: UploadFile = File(...)):
    record = upload_document(collection, file)
    return {'success': True, 'collection': collection, 'document_id': record['id'], 'chunk_count': record['chunks']}


@app.delete('/api/knowledge-bases/{base_id}/documents/{document_id}')
def delete_document(base_id: str, document_id: str):
    with lock:
        registry = read_registry()
        entry = find_base(base_id)
        record = next((doc for doc in entry['documents'] if doc['id'] == document_id), None)
        if record is None:
            raise HTTPException(404, 'Document not found')
        if 'source' not in record:
            raise HTTPException(409, 'Legacy document requires source-path deletion through CLI')
        count = get_system(base_id).vector_store.delete_document(record['source'])
        registry[base_id]['documents'] = [doc for doc in entry['documents'] if doc['id'] != document_id]
        save_registry(registry)
        return {'success': True, 'removed_chunks': count}
