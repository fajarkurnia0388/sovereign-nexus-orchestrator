"""
SNO Knowledge Nexus — v2.0

The Nexus is SNO's hybrid memory system, combining:
  1. Vector Store (Qdrant) — semantic similarity search over stored documents.
  2. Graph Store (NetworkX/Neo4j) — entity-relationship traversal.

Changes from v1.x:
  - FIX ISU-7: Uses nx.DiGraph() (directed) instead of nx.Graph() (undirected).
  - FIX ISU-13: Removed unused ChatMemoryBuffer import.
  - ADD: `store()` method for persisting knowledge from MCP tool.
  - ADD: `health_check()` method.
  - ADD: Graceful degradation — Nexus works with in-memory graph even if
          Qdrant/Neo4j are unavailable (important for PoC / local dev).
  - ADD: Unique document IDs via UUID.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import networkx as nx

from src.config import settings
from src.utils.logger import get_logger

logger = get_logger("memory.nexus")


@dataclass
class DocumentRecord:
    doc_id: str
    content: str
    tags: list[str]
    created_at: str
    entity_name: str = ""


class KnowledgeNexus:
    """
    Hybrid memory combining vector semantic search with graph traversal.

    Architecture:
      - Primary: Qdrant vector store for high-dimensional semantic search.
      - Secondary: NetworkX DiGraph as a local graph fallback (or Neo4j in production).
      - Fallback: In-memory list when Qdrant is unavailable (PoC mode).

    The Nexus is designed for graceful degradation:
      - With Qdrant + Neo4j: Full production capability.
      - With Qdrant only: No graph traversal, semantic search works.
      - Without Qdrant: In-memory fallback — data lost on restart, no semantic search.
    """

    def __init__(self):
        # Directed graph — ISU-7 FIX
        self._graph: nx.DiGraph = nx.DiGraph()

        # In-memory document store (PoC fallback)
        self._documents: list[DocumentRecord] = []

        # Optional: Qdrant vector client
        self._qdrant = self._init_qdrant()

        # Optional: Neo4j driver
        self._neo4j = self._init_neo4j()

    def _init_qdrant(self) -> Any | None:
        """Try to connect to Qdrant; return None if unavailable."""
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import Distance, VectorParams

            client = QdrantClient(url=settings.qdrant_url, timeout=5.0)
            # Ensure collection exists (1536 dims = OpenAI text-embedding-3-small)
            collections = [c.name for c in client.get_collections().collections]
            if settings.qdrant_collection not in collections:
                client.create_collection(
                    collection_name=settings.qdrant_collection,
                    vectors_config=VectorParams(size=1536, distance=Distance.COSINE),
                )
                logger.info(f"Created Qdrant collection '{settings.qdrant_collection}'")
            logger.info(f"Qdrant connected at {settings.qdrant_url}")
            return client
        except Exception as exc:
            logger.warning(f"Qdrant unavailable ({exc}) — using in-memory fallback")
            return None

    def _init_neo4j(self) -> Any | None:
        """Try to connect to Neo4j; return None if unavailable."""
        try:
            from neo4j import GraphDatabase

            driver = GraphDatabase.driver(
                settings.neo4j_url,
                auth=(settings.neo4j_user, settings.neo4j_password),
            )
            driver.verify_connectivity()
            logger.info(f"Neo4j connected at {settings.neo4j_url}")
            return driver
        except Exception as exc:
            logger.warning(f"Neo4j unavailable ({exc}) — using NetworkX DiGraph fallback")
            return None

    # ── Store ────────────────────────────────────────────────────────────────

    async def store(
        self,
        content: str,
        tags: list[str] | None = None,
        entity_name: str = "",
    ) -> dict[str, Any]:
        """
        Persist a document in the Nexus.

        Args:
            content:      Text content to store.
            tags:         Optional metadata tags.
            entity_name:  If set, create/update a named entity node in the graph.

        Returns:
            Dict with doc_id and storage_backend.
        """
        doc_id = str(uuid.uuid4())[:8]
        created_at = datetime.now(tz=timezone.utc).isoformat()
        record = DocumentRecord(
            doc_id=doc_id,
            content=content,
            tags=tags or [],
            created_at=created_at,
            entity_name=entity_name,
        )

        # 1. Vector store (if available)
        if self._qdrant:
            await self._store_in_qdrant(doc_id, content, tags or [], entity_name)
        else:
            self._documents.append(record)

        # 2. Graph node
        if entity_name:
            self._graph.add_node(
                entity_name,
                doc_id=doc_id,
                created_at=created_at,
                tags=tags or [],
                content_preview=content[:100],
            )
            logger.debug(f"Graph node added: '{entity_name}'")

        logger.info(f"Stored doc {doc_id} in Nexus (entity='{entity_name}')")
        return {"doc_id": doc_id, "entity_name": entity_name}

    async def _get_embeddings(self, text: str) -> list[float]:
        """Fetch real embeddings using OpenAI API, or fallback to zero vector if key is missing."""
        if not settings.openai_api_key:
            logger.debug("OPENAI_API_KEY is not set. Using zero vector embedding fallback.")
            return [0.0] * 1536

        try:
            import httpx
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    "https://api.openai.com/v1/embeddings",
                    headers={
                        "Authorization": f"Bearer {settings.openai_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "input": text,
                        "model": "text-embedding-3-small",
                    }
                )
                response.raise_for_status()
                data = response.json()
                return data["data"][0]["embedding"]
        except Exception as exc:
            logger.error(f"Failed to fetch OpenAI embeddings: {exc}. Falling back to zero vector.")
            return [0.0] * 1536

    async def _store_in_qdrant(
        self,
        doc_id: str,
        content: str,
        tags: list[str],
        entity_name: str,
    ) -> None:
        """Store a document in Qdrant with its embedding vector."""
        try:
            from qdrant_client.models import PointStruct

            # Retrieve real embeddings from OpenAI (or fallback)
            vector = await self._get_embeddings(content)
            self._qdrant.upsert(
                collection_name=settings.qdrant_collection,
                points=[
                    PointStruct(
                        id=abs(hash(doc_id)) % (2**63),
                        vector=vector,
                        payload={
                            "doc_id": doc_id,
                            "content": content,
                            "tags": tags,
                            "entity_name": entity_name,
                        },
                    )
                ],
            )
        except Exception as exc:
            logger.warning(f"Qdrant store failed for {doc_id}: {exc}")

    # ── Query ────────────────────────────────────────────────────────────────

    async def query(self, query: str, top_k: int = 5) -> dict[str, Any]:
        """
        Execute a hybrid query: semantic search + graph traversal.

        Args:
            query:  Natural language search query.
            top_k:  Maximum semantic results.

        Returns:
            Dict with semantic_results, graph_context, and metadata.
        """
        semantic = await self._semantic_search(query, top_k)
        graph_ctx = self._graph_context(query)

        return {
            "query": query,
            "semantic_results": semantic,
            "graph_context": graph_ctx,
            "total_documents": len(self._documents) if not self._qdrant else "N/A (Qdrant)",
            "graph_nodes": self._graph.number_of_nodes(),
            "graph_edges": self._graph.number_of_edges(),
        }

    async def _semantic_search(self, query: str, top_k: int) -> list[dict]:
        """Return semantically similar documents."""
        if self._qdrant:
            try:
                # Retrieve real embeddings from OpenAI (or fallback)
                query_vector = await self._get_embeddings(query)
                results = self._qdrant.search(
                    collection_name=settings.qdrant_collection,
                    query_vector=query_vector,
                    limit=top_k,
                )
                return [
                    {
                        "score": round(r.score, 4),
                        "content": r.payload.get("content", "")[:200],
                        "doc_id": r.payload.get("doc_id"),
                        "tags": r.payload.get("tags", []),
                    }
                    for r in results
                ]
            except Exception as exc:

                logger.warning(f"Qdrant search failed: {exc}")

        # In-memory fallback: simple keyword match
        query_lower = query.lower()
        results = [
            {
                "score": 0.5,
                "content": doc.content[:200],
                "doc_id": doc.doc_id,
                "tags": doc.tags,
            }
            for doc in self._documents
            if query_lower in doc.content.lower()
        ]
        return results[:top_k]

    def _graph_context(self, query: str) -> dict:
        """Return graph context: matching nodes and their neighbors."""
        if self._graph.number_of_nodes() == 0:
            return {"nodes": [], "edges": [], "message": "Knowledge graph is empty"}

        query_lower = query.lower()
        matching_nodes = [
            n for n in self._graph.nodes if query_lower in str(n).lower()
        ]

        result_nodes = []
        result_edges = []
        for node in matching_nodes[:5]:
            attrs = dict(self._graph.nodes[node])
            result_nodes.append({"id": node, **attrs})
            for _, neighbor, data in self._graph.out_edges(node, data=True):
                result_edges.append({"from": node, "to": neighbor, "relation": data})

        return {"nodes": result_nodes, "edges": result_edges}

    def add_relationship(
        self,
        source: str,
        target: str,
        relation: str,
        weight: float = 1.0,
    ) -> None:
        """
        Add a directed relationship between two entities in the graph.

        Example:
            nexus.add_relationship("Hermes", "SNO", "controls")
            nexus.add_relationship("SNO", "Qdrant", "uses")
        """
        self._graph.add_edge(source, target, relation=relation, weight=weight)
        logger.debug(f"Graph edge: {source} --[{relation}]--> {target}")

    # ── Health ───────────────────────────────────────────────────────────────

    async def health_check(self) -> dict[str, str]:
        status = {}

        # Qdrant
        if self._qdrant:
            try:
                self._qdrant.get_collections()
                status["qdrant"] = "healthy"
            except Exception as exc:
                status["qdrant"] = f"unhealthy: {exc}"
        else:
            status["qdrant"] = "not configured (in-memory fallback active)"

        # Neo4j
        if self._neo4j:
            try:
                with self._neo4j.session() as session:
                    session.run("RETURN 1")
                status["neo4j"] = "healthy"
            except Exception as exc:
                status["neo4j"] = f"unhealthy: {exc}"
        else:
            status["neo4j"] = "not configured (networkx DiGraph active)"

        status["graph_nodes"] = str(self._graph.number_of_nodes())
        status["in_memory_docs"] = str(len(self._documents))

        return status

    def close(self) -> None:
        if self._neo4j:
            self._neo4j.close()
        logger.info("KnowledgeNexus closed.")
