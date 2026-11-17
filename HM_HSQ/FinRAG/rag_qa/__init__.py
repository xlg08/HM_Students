"""Public RAG components, loaded on demand."""
__all__ = ['VectorStore', 'RAGSystem']

def __getattr__(name):
    if name == 'VectorStore':
        from .core.vector_store import VectorStore
        return VectorStore
    if name == 'RAGSystem':
        from .core.rag_system import RAGSystem
        return RAGSystem
    raise AttributeError(name)
