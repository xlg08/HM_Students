"""Generic RAG command-line and application entry point."""
import argparse
from pathlib import Path
from base import Config
from rag_qa.core.rag_system import RAGSystem

class IntegratedQASystem:
    def __init__(self, config=None, vector_store=None, llm=None):
        self.config = config or Config()
        if vector_store is None:
            from rag_qa.core.vector_store import VectorStore
            vector_store = VectorStore(self.config)
        self.vector_store = vector_store
        self.rag_system = RAGSystem(vector_store, llm or self.call_llm, self.config)
        self._history = {}

    def call_llm(self, prompt):
        from openai import OpenAI
        if not self.config.DASHSCOPE_API_KEY:
            raise ValueError('请设置 RAG_API_KEY 或 DASHSCOPE_API_KEY 环境变量')
        with OpenAI(api_key=self.config.DASHSCOPE_API_KEY, base_url=self.config.DASHSCOPE_BASE_URL) as client:
            with client.chat.completions.create(model=self.config.LLM_MODEL,
                    messages=[{'role': 'user', 'content': prompt}], stream=True, timeout=60) as stream:
                for chunk in stream:
                    if chunk.choices and chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content

    def ingest(self, path, source=None, document_name=None):
        from rag_qa.core.document_processor import process_documents
        docs = process_documents(path, self.config.PARENT_CHUNK_SIZE, self.config.CHILD_CHUNK_SIZE, self.config.CHUNK_OVERLAP)
        if source:
            import hashlib
            for doc in docs:
                doc.metadata['source'] = source
                doc.metadata['document'] = document_name or Path(source).name
                doc.metadata['document_id'] = hashlib.sha256(source.encode()).hexdigest()
                doc.metadata['chunk_id'] = hashlib.sha256((source + doc.metadata['chunk_id']).encode()).hexdigest()
        self.vector_store.add_documents(docs)
        return len(docs)

    def get_session_history(self, session_id):
        return [dict(turn) for turn in self._history.get(session_id, [])]

    def clear_session_history(self, session_id):
        self._history.pop(session_id, None)
        return True

    def query(self, query, source_filter=None, session_id=None):
        parts = []
        history = self.get_session_history(session_id) if session_id else []
        for token in self.rag_system.generate_answer(query, source_filter, history):
            parts.append(token)
            yield token, False
        if session_id:
            self._history[session_id] = (history + [{'question': query, 'answer': ''.join(parts)}])[-5:]
        yield '', True

    def close(self):
        self.vector_store.close()

def main():
    parser = argparse.ArgumentParser(description='通用文档 RAG')
    parser.add_argument('--config', default=None)
    parser.add_argument('--knowledge-base', '--collection', default=None)
    parser.add_argument('--domain', default=None)
    commands = parser.add_subparsers(dest='command', required=True)
    ingest = commands.add_parser('ingest', help='导入文件或目录')
    ingest.add_argument('path')
    ask = commands.add_parser('ask', help='单次问答')
    ask.add_argument('question')
    delete = commands.add_parser('delete-document', help='??????????')
    delete.add_argument('source')
    commands.add_parser('chat', help='交互问答，exit 退出')
    args = parser.parse_args()
    config = Config(args.config, args.knowledge_base)
    if args.domain:
        config.DOMAIN = args.domain
    from rag_qa.core.vector_store import VectorStore
    system = IntegratedQASystem(config, vector_store=VectorStore(config, create=args.command == 'ingest'))
    try:
        if args.command == 'ingest':
            print(f'已导入 {system.ingest(args.path)} 个文档块')
        elif args.command == 'delete-document':
            print(system.vector_store.delete_document(str(Path(args.source).resolve())))
        elif args.command == 'ask':
            for token, _ in system.query(args.question):
                print(token, end='', flush=True)
            print()
        else:
            while True:
                question = input('\n问题 > ').strip()
                if question.lower() == 'exit':
                    break
                if question:
                    for token, _ in system.query(question, session_id='cli'):
                        print(token, end='', flush=True)
                    print()
    finally:
        system.close()

if __name__ == '__main__':
    main()
