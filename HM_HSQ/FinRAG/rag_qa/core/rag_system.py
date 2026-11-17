from base import Config
from .prompts import RAGPrompts

class RAGSystem:
    def __init__(self, vector_store, llm, config=None):
        self.vector_store = vector_store
        self.llm = llm
        self.config = config or vector_store.config

    def retrieve_and_merge(self, query, source_filter=None):
        if not query.strip():
            raise ValueError('问题不能为空')
        return self.vector_store.hybrid_search_with_rerank(query, source_filter=source_filter)

    def generate_answer(self, query, source_filter=None, history=None):
        docs = self.retrieve_and_merge(query, source_filter)
        if not docs:
            yield '当前知识库未检索到参考资料，请先导入相关文档。'
            return
        context = '\n\n'.join(f"[{i}] {doc.metadata['source']} 第{doc.metadata['page']}页\n{doc.page_content}" for i, doc in enumerate(docs, 1))
        prompt = RAGPrompts.rag_prompt().format(domain=self.config.DOMAIN, instructions=self.config.INSTRUCTIONS,
            history=str((history or [])[-5:]), context=context, question=query)
        answer = self.llm(prompt)
        if isinstance(answer, str):
            yield answer
        else:
            yield from answer
        yield '\n\n参考来源\n' + '\n'.join(f"[{i}] {doc.metadata['source']} 第{doc.metadata['page']}页" for i, doc in enumerate(docs, 1))
