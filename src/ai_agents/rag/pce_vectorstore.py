"""ChromaDB persistent vectorstore for PCE catalog entries.

Also holds a separate collection for invoice embeddings used in
semantic duplicate detection.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.cost_catalog.catalog import CostCatalogEntry

logger = logging.getLogger(__name__)

_CHROMADB_PATH = os.getenv("CHROMADB_PATH", "./data/chromadb")
_PCE_COLLECTION = "pce_catalog"
_INVOICE_COLLECTION = "invoice_embeddings"


class PCEVectorStore:
    """Manages two ChromaDB collections: PCE catalog + invoice embeddings."""

    _instance: "PCEVectorStore | None" = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._client = None
        self._pce_col = None
        self._inv_col = None
        self._available = False
        self._init_client()

    @classmethod
    def get(cls) -> "PCEVectorStore":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _init_client(self) -> None:
        try:
            import chromadb
            os.makedirs(_CHROMADB_PATH, exist_ok=True)
            self._client = chromadb.PersistentClient(path=_CHROMADB_PATH)
            self._pce_col = self._client.get_or_create_collection(
                name=_PCE_COLLECTION,
                metadata={"hnsw:space": "cosine"},
            )
            self._inv_col = self._client.get_or_create_collection(
                name=_INVOICE_COLLECTION,
                metadata={"hnsw:space": "cosine"},
            )
            self._available = True
            logger.info("chromadb_ready path=%s", _CHROMADB_PATH)
        except Exception as exc:
            logger.warning("chromadb_unavailable: %s — RAG + semantic dedup disabled", exc)
            self._available = False

    @property
    def available(self) -> bool:
        return self._available

    # ── PCE catalog ───────────────────────────────────────────────────────────

    def initialize_pce(self, entries: list["CostCatalogEntry"]) -> None:
        """Index PCE catalog entries. Skips if already indexed."""
        if not self._available:
            return
        if self._pce_col.count() == len(entries):
            logger.info("pce_vectorstore_already_indexed count=%d", len(entries))
            return
        self._pce_col.delete(where={"$ne": {"id": "__none__"}}) if self._pce_col.count() > 0 else None
        self._index_pce(entries)

    def _index_pce(self, entries: list["CostCatalogEntry"]) -> None:
        from src.ai_agents.rag.embedder import PCEEmbedder
        embedder = PCEEmbedder.get()
        texts = [f"{e.label} {' '.join(e.keywords)}" for e in entries]
        vecs = embedder.embed_batch(texts)
        ids, embeddings, metadatas, documents = [], [], [], []
        for entry, vec, text in zip(entries, vecs, texts):
            if vec is None:
                continue
            ids.append(entry.id)
            embeddings.append(vec)
            documents.append(text)
            metadatas.append({
                "id": entry.id,
                "label": entry.label,
                "compte": entry.compte,
                "charge_type": entry.type_charge.value,
                "tva_rate": str(entry.tva_rate),
            })
        if ids:
            self._pce_col.add(ids=ids, embeddings=embeddings,
                              documents=documents, metadatas=metadatas)
            logger.info("pce_vectorstore_indexed count=%d", len(ids))

    def search_pce(self, query_text: str, n_results: int = 3) -> list[dict]:
        """Return top n PCE catalog matches with similarity scores."""
        if not self._available:
            return []
        from src.ai_agents.rag.embedder import PCEEmbedder
        vec = PCEEmbedder.get().embed(query_text)
        if vec is None:
            return []
        try:
            res = self._pce_col.query(
                query_embeddings=[vec],
                n_results=min(n_results, max(1, self._pce_col.count())),
                include=["metadatas", "distances"],
            )
            results = []
            for meta, dist in zip(res["metadatas"][0], res["distances"][0]):
                results.append({
                    **meta,
                    "similarity": round(1 - dist, 4),
                })
            return results
        except Exception as exc:
            logger.warning("pce_search_error: %s", exc)
            return []

    def reindex_pce(self, entries: list["CostCatalogEntry"]) -> None:
        if not self._available:
            return
        try:
            self._client.delete_collection(_PCE_COLLECTION)
            self._pce_col = self._client.get_or_create_collection(
                name=_PCE_COLLECTION, metadata={"hnsw:space": "cosine"}
            )
        except Exception:
            pass
        self._index_pce(entries)

    # ── Invoice embeddings (semantic duplicate detection) ─────────────────────

    def store_invoice_embedding(self, invoice_id: str, embedding_text: str,
                                 invoice_number: str | None = None) -> None:
        if not self._available:
            return
        from src.ai_agents.rag.embedder import PCEEmbedder
        vec = PCEEmbedder.get().embed(embedding_text)
        if vec is None:
            return
        try:
            # upsert: delete existing entry for this invoice if any
            existing = self._inv_col.get(ids=[invoice_id])
            if existing["ids"]:
                self._inv_col.delete(ids=[invoice_id])
            self._inv_col.add(
                ids=[invoice_id],
                embeddings=[vec],
                documents=[embedding_text],
                metadatas=[{"invoice_number": invoice_number or ""}],
            )
        except Exception as exc:
            logger.warning("invoice_embedding_store_error: %s", exc)

    def search_similar_invoices(self, embedding_text: str, n_results: int = 3,
                                 exclude_id: str | None = None) -> list[dict]:
        """Find semantically similar invoices for duplicate detection."""
        if not self._available or self._inv_col.count() == 0:
            return []
        from src.ai_agents.rag.embedder import PCEEmbedder
        vec = PCEEmbedder.get().embed(embedding_text)
        if vec is None:
            return []
        try:
            count = self._inv_col.count()
            res = self._inv_col.query(
                query_embeddings=[vec],
                n_results=min(n_results + 1, count),
                include=["metadatas", "distances"],
            )
            results = []
            for id_, meta, dist in zip(res["ids"][0], res["metadatas"][0], res["distances"][0]):
                if id_ == exclude_id:
                    continue
                results.append({
                    "invoice_id": id_,
                    "invoice_number": meta.get("invoice_number", ""),
                    "similarity": round(1 - dist, 4),
                })
            return results[:n_results]
        except Exception as exc:
            logger.warning("invoice_search_error: %s", exc)
            return []
