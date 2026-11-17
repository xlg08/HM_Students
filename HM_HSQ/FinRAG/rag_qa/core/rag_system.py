from .prompts import RAGPrompts
from .interfaces import Retriever
from .context_builder import build_context


class RAGSystem:
    def __init__(self, vector_store: Retriever, llm, config=None):
        self.vector_store = vector_store
        self.llm = llm
        self.config = config or vector_store.config

    def retrieve_and_merge(self, query, source_filter=None, top_k=None):
        if not query.strip():
            raise ValueError('问题不能为空')
        if top_k is not None and not 1 <= top_k <= 100:
            raise ValueError('top_k must be between 1 and 100')
        return self.vector_store.hybrid_search_with_rerank(query, k=top_k, source_filter=source_filter)

    def prepare(self, query, source_filter=None, history=None, top_k=None):
        docs = self.retrieve_and_merge(query, source_filter, top_k)
        context, sources = build_context(docs, self.config.MAX_CONTEXT_TOKENS)
        prompt = RAGPrompts.rag_prompt().format(domain=self.config.DOMAIN, instructions=self.config.INSTRUCTIONS,
            history=str((history or [])[-5:])[:4000], context=context, question=query)
        return prompt, sources

    def stream_prepared(self, prompt, sources):
        if not sources:
            yield '当前知识库没有可用的参考资料，请导入相关文档或调整检索条件。'
            return
        answer = self.llm(prompt)
        if isinstance(answer, str):
            yield answer
        else:
            yield from answer

    def answer(self, query, top_k=None):
        prompt, sources = self.prepare(query, top_k=top_k)
        return {'answer': ''.join(self.stream_prepared(prompt, sources)),
                'collection': self.config.KNOWLEDGE_BASE, 'sources': sources,
                'warnings': sorted({source['warning'] for source in sources if 'warning' in source})}

    def generate_answer(self, query, source_filter=None, history=None):
        prompt, sources = self.prepare(query, source_filter, history)
        yield from self.stream_prepared(prompt, sources)
        if sources:
            yield '\n\n参考来源\n' + '\n'.join(f"[{i}] {s['document']} 第{s['page']}页 ({s['location']})" for i, s in enumerate(sources, 1))

        for warning in sorted({source['warning'] for source in sources if 'warning' in source}):
            yield '\n' + warning
