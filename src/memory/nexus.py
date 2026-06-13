"""
SNO Knowledge Nexus — Hybrid Memory Architecture
-------------------------------------------------
Combines two complementary search strategies:

  1. Semantic / Vector search  →  LlamaIndex + Qdrant (production)
                                   Mocked in local/dev mode
  2. Relational / Graph search →  NetworkX in-memory (dev)
                                   Neo4j in production

Production upgrade path:
  - Replace the NetworkX mock with a Neo4j driver.
  - Replace the None vector_index with a real LlamaIndex VectorStoreIndex
    backed by QdrantVectorStore.
"""
import logging
from typing import Any, Dict, List, Optional

import networkx as nx

logger = logging.getLogger(__name__)

# ── Graceful LlamaIndex import ────────────────────────────────────────────────
# llama-index is split into llama-index-core + provider packages since v0.10.
# We import optionally so the app starts even without the full AI stack.
try:
    from llama_index.core import VectorStoreIndex  # noqa: F401  (used in type hints)
    LLAMA_INDEX_AVAILABLE = True
    logger.debug("llama-index-core detected — vector search enabled.")
except ImportError:
    LLAMA_INDEX_AVAILABLE = False
    logger.warning(
        "llama-index-core not installed — semantic search will use mock responses. "
        "Install with: pip install llama-index-core"
    )


class KnowledgeNexus:
    """
    Hybrid Memory combining Vector (semantic) and Graph (relational) search.

    FIX: Changed nx.Graph() (undirected) to nx.DiGraph() (directed).
    Relations like 'controls' and 'implemented_via' have clear directionality
    that was lost with an undirected graph.

    FIX: Removed unused `from llama_index.core.memory import ChatMemoryBuffer`
    import — it was imported but never referenced anywhere in the original code.
    """

    def __init__(self):
        # FIX: Use DiGraph for directed edges (A→B is semantically different from B→A)
        self._graph: nx.DiGraph = nx.DiGraph()
        self._vector_index: Optional[Any] = None
        self._init_graph()
        self._init_vector_store()

    # ── Initialisation ────────────────────────────────────────

    def _init_graph(self) -> None:
        """Seed the in-memory graph with initial SNO domain knowledge."""
        edges = [
            ("SNO", "MCP", "implemented_via"),
            ("SNO", "LangGraph", "powered_by"),
            ("Hermes", "SNO", "controls"),
            ("SNO", "Knowledge Nexus", "accesses"),
            ("Knowledge Nexus", "Qdrant", "uses_vector_store"),
            ("Knowledge Nexus", "Neo4j", "uses_graph_store"),
            ("Playbook", "LangGraph", "compiled_into"),
            ("SNO Engine", "Redis", "queues_via"),
        ]
        for src, dst, rel in edges:
            self._graph.add_edge(src, dst, relation=rel)
        logger.debug("In-memory knowledge graph initialised (%d edges).", self._graph.number_of_edges())

    def _init_vector_store(self) -> None:
        """
        Initialise the vector index.

        In production, connect to Qdrant and build a VectorStoreIndex over
        your document corpus.  In PoC mode, the index stays None and
        semantic_search() returns a mock response.
        """
        if not LLAMA_INDEX_AVAILABLE:
            self._vector_index = None
            return
        try:
            # Production example (not active in PoC):
            #   from llama_index.core import VectorStoreIndex, SimpleDirectoryReader
            #   from llama_index.vector_stores.qdrant import QdrantVectorStore
            #   reader = SimpleDirectoryReader("./docs")
            #   documents = reader.load_data()
            #   self._vector_index = VectorStoreIndex.from_documents(documents)
            self._vector_index = None
            logger.info("LlamaIndex available — vector index placeholder ready (no docs loaded in PoC).")
        except Exception as exc:
            logger.error("Vector store initialisation failed: %s", exc)
            self._vector_index = None

    # ── Search Methods ────────────────────────────────────────

    async def semantic_search(self, query: str) -> str:
        """Return semantic matches from the vector index (or a mock response)."""
        if self._vector_index is None:
            return f"[Mock Semantic] Simulated vector match for: '{query}'"
        try:
            engine = self._vector_index.as_query_engine()
            response = await engine.aquery(query)
            return str(response)
        except Exception as exc:
            logger.error("Semantic search failed: %s", exc)
            return f"Semantic search error: {exc}"

    def graph_search(self, query: str) -> List[str]:
        """
        Find directed edges in the knowledge graph where a node name appears
        in the query string.  Returns triples as 'A --[relation]--> B' strings.
        """
        results: List[str] = []
        q = query.lower()
        for node in self._graph.nodes():
            if node.lower() in q:
                # Outgoing edges (node is the subject)
                for succ in self._graph.successors(node):
                    rel = self._graph[node][succ].get("relation", "connected_to")
                    results.append(f"{node} --[{rel}]--> {succ}")
                # Incoming edges (node is the object)
                for pred in self._graph.predecessors(node):
                    rel = self._graph[pred][node].get("relation", "connected_to")
                    results.append(f"{pred} --[{rel}]--> {node}")
        return results

    async def hybrid_query(self, query: str) -> Dict[str, Any]:
        """Run both semantic and graph search; return merged results."""
        semantic = await self.semantic_search(query)
        relational = self.graph_search(query)
        return {
            "semantic": semantic,
            "relational": relational,
            "combined": f"{semantic} | Relations: {', '.join(relational)}",
        }

    # ── Mutation ──────────────────────────────────────────────

    def add_knowledge(self, subject: str, predicate: str, obj: str) -> None:
        """Manually add a directed triple to the knowledge graph."""
        self._graph.add_edge(subject, obj, relation=predicate)
        logger.info("Knowledge added: %s --[%s]--> %s", subject, predicate, obj)


nexus = KnowledgeNexus()
