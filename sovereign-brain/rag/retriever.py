"""
Sovereign Brain — Qdrant RAG Retriever
=======================================
Retrieves authoritative policy documents to ground LLM responses.

Pipeline:
  1. Embed query using fastembed (ONNX-based, CPU-only, no PyTorch/CUDA)
  2. Search Qdrant vector collection with metadata filters
  3. Apply confidence threshold (reject below QDRANT_SCORE_THRESHOLD)
  4. Return RetrievalResult (docs + full audit metadata)

Design principles:
  - fastembed: ~50MB vs 3GB for sentence-transformers+torch (ONNX, CPU-only)
  - Score threshold prevents hallucination from low-relevance results
  - Metadata filters allow jurisdiction/benefit-scoped retrieval
  - Full audit metadata returned for sovereign audit layer compliance
"""

import logging
import uuid
from dataclasses import dataclass, field
from typing import Optional

from fastembed import TextEmbedding
from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    ScoredPoint,
    VectorParams,
)

log = logging.getLogger("sovereign.rag")

# fastembed model — BAAI/bge-small-en-v1.5 is high quality, 384-dim, CPU-fast
FASTEMBED_MODEL = "BAAI/bge-small-en-v1.5"
EMBEDDING_DIM = 384


@dataclass
class RetrievalAudit:
    """
    Full retrieval audit record — proves what was retrieved, what filters
    were applied, and how many documents were considered vs returned.
    Stored in the audit_log.retrieval_audit JSONB column.
    """
    retrieval_id: str
    filters_applied: dict
    documents_considered: int      # total points in collection (or filtered subset)
    documents_returned: int
    score_threshold: float
    cross_boundary_attempt: bool   # True if requested benefit_id not in any result
    documents: list[dict]          # per-doc audit entries (id, title, score, source, type, date)

    def to_dict(self) -> dict:
        return {
            "retrieval_id": self.retrieval_id,
            "filters_applied": self.filters_applied,
            "documents_considered": self.documents_considered,
            "documents_returned": self.documents_returned,
            "score_threshold": self.score_threshold,
            "cross_boundary_attempt": self.cross_boundary_attempt,
            "documents": self.documents,
        }


@dataclass
class RetrievalResult:
    """Combined output of a RAG retrieval: documents for the pipeline + audit record."""
    docs: list[dict]           # Full doc objects (including content) for system prompt
    audit: RetrievalAudit      # Audit-only record (no full content, for log storage)


class RAGRetriever:
    """Qdrant-backed policy document retriever with fastembed local embedding."""

    def __init__(self, settings):
        self.settings = settings
        self._client: Optional[AsyncQdrantClient] = None
        self._embedder: Optional[TextEmbedding] = None

    async def connect(self):
        """Initialise Qdrant client and fastembed embedding model."""
        self._client = AsyncQdrantClient(
            host=self.settings.qdrant_host,
            port=self.settings.qdrant_port,
        )

        # Ensure collection exists
        collections = await self._client.get_collections()
        col_names = [c.name for c in collections.collections]
        if self.settings.qdrant_collection not in col_names:
            await self._client.create_collection(
                collection_name=self.settings.qdrant_collection,
                vectors_config=VectorParams(
                    size=EMBEDDING_DIM,
                    distance=Distance.COSINE,
                ),
            )
            log.info(f"Created Qdrant collection: {self.settings.qdrant_collection}")

        # Load fastembed model (ONNX — downloads once, ~50MB, CPU-only)
        log.info(f"Loading fastembed model: {FASTEMBED_MODEL}")
        self._embedder = TextEmbedding(model_name=FASTEMBED_MODEL)
        log.info("RAG retriever ready")

    async def retrieve(
        self,
        query: str,
        benefit_id: Optional[str] = None,
        top_k: Optional[int] = None,
    ) -> RetrievalResult:
        """
        Retrieve top-k policy documents relevant to the query.
        Applies confidence threshold — returns empty result if nothing is authoritative.
        Always returns a RetrievalResult with full audit metadata.
        """
        retrieval_id = str(uuid.uuid4())
        score_threshold = self.settings.qdrant_score_threshold
        k = top_k or self.settings.qdrant_top_k

        filters_applied: dict = {"score_threshold": score_threshold}
        if benefit_id:
            filters_applied["benefit_id"] = benefit_id

        if not self._client or not self._embedder:
            return RetrievalResult(
                docs=[],
                audit=RetrievalAudit(
                    retrieval_id=retrieval_id,
                    filters_applied=filters_applied,
                    documents_considered=0,
                    documents_returned=0,
                    score_threshold=score_threshold,
                    cross_boundary_attempt=False,
                    documents=[],
                ),
            )

        query_vector = self._embed(query)

        # Optional: filter by benefit/jurisdiction
        query_filter = None
        if benefit_id:
            query_filter = Filter(
                must=[
                    FieldCondition(
                        key="benefit_ids",
                        match=MatchValue(value=benefit_id),
                    )
                ]
            )

        # Get total documents considered (collection count)
        try:
            collection_info = await self._client.get_collection(self.settings.qdrant_collection)
            documents_considered = collection_info.points_count or 0
        except Exception:
            documents_considered = 0

        try:
            results: list[ScoredPoint] = await self._client.search(
                collection_name=self.settings.qdrant_collection,
                query_vector=query_vector,
                limit=k,
                score_threshold=score_threshold,
                query_filter=query_filter,
                with_payload=True,
            )
        except Exception as e:
            log.error(f"Qdrant search error: {e}")
            return RetrievalResult(
                docs=[],
                audit=RetrievalAudit(
                    retrieval_id=retrieval_id,
                    filters_applied=filters_applied,
                    documents_considered=documents_considered,
                    documents_returned=0,
                    score_threshold=score_threshold,
                    cross_boundary_attempt=False,
                    documents=[],
                ),
            )

        docs = []
        audit_docs = []
        returned_benefit_ids: set[str] = set()

        for point in results:
            payload = point.payload or {}
            doc_benefit_ids = payload.get("benefit_ids", [])
            returned_benefit_ids.update(doc_benefit_ids)

            # Full document object (including content) for system prompt building
            docs.append({
                "id": str(point.id),
                "score": round(point.score, 4),
                "title": payload.get("title", "Policy Document"),
                "source": payload.get("source", "Government Policy"),
                "content": payload.get("content", ""),
                "benefit_ids": doc_benefit_ids,
                "jurisdiction": payload.get("jurisdiction", ""),
                "document_type": payload.get("document_type", "policy"),
                "effective_date": payload.get("effective_date", ""),
            })

            # Audit-only entry (no full content — keeps audit log compact)
            audit_docs.append({
                "id": str(point.id),
                "title": payload.get("title", ""),
                "score": round(point.score, 4),
                "source": payload.get("source", ""),
                "document_type": payload.get("document_type", ""),
                "effective_date": payload.get("effective_date", ""),
                "benefit_ids": doc_benefit_ids,
                "jurisdiction": payload.get("jurisdiction", ""),
            })

        # Detect cross-boundary attempt: filter was by benefit_id but results
        # contain documents from outside that benefit scope
        cross_boundary = False
        if benefit_id and returned_benefit_ids and benefit_id not in returned_benefit_ids:
            cross_boundary = True
            log.warning(
                f"Cross-boundary retrieval: requested {benefit_id}, "
                f"got docs for {returned_benefit_ids}"
            )

        log.info(
            f"RAG: retrieved {len(docs)}/{documents_considered} docs "
            f"(threshold={score_threshold}, filter={benefit_id})"
        )

        return RetrievalResult(
            docs=docs,
            audit=RetrievalAudit(
                retrieval_id=retrieval_id,
                filters_applied=filters_applied,
                documents_considered=documents_considered,
                documents_returned=len(docs),
                score_threshold=score_threshold,
                cross_boundary_attempt=cross_boundary,
                documents=audit_docs,
            ),
        )

    async def upsert_document(self, doc_id: int, payload: dict, text: str):
        """Insert or update a policy document in the vector store."""
        if not self._client or not self._embedder:
            raise RuntimeError("RAG not connected")

        vector = self._embed(text)
        from qdrant_client.models import PointStruct
        await self._client.upsert(
            collection_name=self.settings.qdrant_collection,
            points=[PointStruct(id=doc_id, vector=vector, payload=payload)],
        )

    async def collection_info(self) -> dict:
        """Return collection stats."""
        if not self._client:
            return {}
        info = await self._client.get_collection(self.settings.qdrant_collection)
        return {
            "name": self.settings.qdrant_collection,
            "vectors_count": info.vectors_count,
            "points_count": info.points_count,
        }

    def _embed(self, text: str) -> list:
        """Embed text using fastembed (ONNX, CPU, no GPU required)."""
        embeddings = list(self._embedder.embed([text]))
        return embeddings[0].tolist()
