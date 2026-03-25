# src/orchestrator/tool_retriever.py
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import OllamaEmbeddings
from langchain_core.documents import Document

class ToolRetriever:
    def __init__(self, tools: list, k: int=40):
        embeddings = OllamaEmbeddings(model="nomic-embed-text")
        docs=[
            Document(
                page_content=f"{t.name}: {t.description}",
                metadata={"tool_name": t.name}
            )
            for t in tools
        ]
        self._tools = tools
        self._store = Chroma.from_documents(docs, embeddings)
        self._k = k

    def get(self, query: str) -> list:
        results = self._store.as_retriever(search_kwargs={"k": self._k}).invoke(query)
        names = {r.metadata["tool_name"] for r in results}
        return [t for t in self._tools if t.name in names]
