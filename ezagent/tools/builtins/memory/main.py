"""Prebuilt memory tool for ezagent.

Provides persistent vector-based memory using Milvus Lite (embedded)
and sentence-transformers for local embeddings.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastmcp import FastMCP

mcp = FastMCP("memory")

# ---------------------------------------------------------------------------
# Lazy-initialised globals
# ---------------------------------------------------------------------------
_milvus_client = None
_embed_model = None

DEFAULT_COLLECTION = "memory"
COLLECTION_PREFIX = "ezagent_"
EMBEDDING_DIM = 384  # all-MiniLM-L6-v2


def _full_collection_name(collection: str) -> str:
    """Prefix user-facing collection name to avoid Milvus namespace clashes."""
    return f"{COLLECTION_PREFIX}{collection}"


def _get_db_path() -> Path:
    project_dir = os.environ.get("EZAGENT_PROJECT_DIR", ".")
    db_dir = Path(project_dir) / ".ezagent" / "memory"
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / "milvus.db"


def _get_client():
    global _milvus_client
    if _milvus_client is None:
        from pymilvus import MilvusClient

        _milvus_client = MilvusClient(str(_get_db_path()))
    return _milvus_client


def _ensure_collection(name: str) -> None:
    """Create the collection if it doesn't already exist."""
    client = _get_client()
    if not client.has_collection(name):
        from pymilvus import CollectionSchema, DataType, FieldSchema

        fields = [
            FieldSchema(
                name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=64
            ),
            FieldSchema(
                name="vector", dtype=DataType.FLOAT_VECTOR, dim=EMBEDDING_DIM
            ),
            FieldSchema(
                name="content", dtype=DataType.VARCHAR, max_length=65535
            ),
            FieldSchema(
                name="agent_name", dtype=DataType.VARCHAR, max_length=256
            ),
            FieldSchema(name="tags", dtype=DataType.VARCHAR, max_length=1024),
            FieldSchema(
                name="created_at", dtype=DataType.VARCHAR, max_length=64
            ),
        ]
        schema = CollectionSchema(fields=fields)
        client.create_collection(
            collection_name=name,
            schema=schema,
        )
        index_params = client.prepare_index_params()
        index_params.add_index(
            field_name="vector",
            index_type="FLAT",
            metric_type="COSINE",
        )
        client.create_index(
            collection_name=name,
            index_params=index_params,
        )


def _get_embed_model():
    global _embed_model
    if _embed_model is None:
        from sentence_transformers import SentenceTransformer

        _embed_model = SentenceTransformer("all-MiniLM-L6-v2")
    return _embed_model


def _embed(text: str) -> list[float]:
    model = _get_embed_model()
    return model.encode(text, normalize_embeddings=True).tolist()


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
def memory_store(
    content: str,
    collection: Optional[str] = None,
    tags: Optional[str] = None,
    agent_name: Optional[str] = None,
) -> str:
    """Store a new memory.

    Args:
        content: The text content to remember.
        collection: Optional collection name (e.g. "conversations", "patterns"). Defaults to "memory".
        tags: Optional comma-separated tags for categorisation.
        agent_name: Optional agent name to associate with this memory.
    """
    col = _full_collection_name(collection or DEFAULT_COLLECTION)
    _ensure_collection(col)
    client = _get_client()
    memory_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    vector = _embed(content)

    client.insert(
        collection_name=col,
        data=[
            {
                "id": memory_id,
                "vector": vector,
                "content": content,
                "agent_name": agent_name or "",
                "tags": tags or "",
                "created_at": created_at,
            }
        ],
    )

    return json.dumps(
        {"status": "stored", "id": memory_id, "collection": collection or DEFAULT_COLLECTION, "created_at": created_at}
    )


@mcp.tool()
def memory_search(
    query: str,
    collection: Optional[str] = None,
    top_k: int = 5,
    agent_name: Optional[str] = None,
    tags: Optional[str] = None,
) -> str:
    """Search memories by semantic similarity.

    Args:
        query: The search query text.
        collection: Optional collection name to search in. Defaults to "memory".
        top_k: Maximum number of results to return (default 5).
        agent_name: Optional filter to only search memories from this agent.
        tags: Optional comma-separated tags to filter by.
    """
    col = _full_collection_name(collection or DEFAULT_COLLECTION)
    _ensure_collection(col)
    client = _get_client()
    vector = _embed(query)

    # Build filter expression
    filters = []
    if agent_name:
        filters.append(f'agent_name == "{agent_name}"')
    if tags:
        for tag in tags.split(","):
            tag = tag.strip()
            if tag:
                filters.append(f'tags like "%{tag}%"')

    filter_expr = " and ".join(filters) if filters else ""

    results = client.search(
        collection_name=col,
        data=[vector],
        limit=top_k,
        output_fields=["content", "agent_name", "tags", "created_at"],
        filter=filter_expr if filter_expr else None,
    )

    hits = []
    for hit in results[0]:
        entity = hit.get("entity", {})
        hits.append(
            {
                "id": hit.get("id"),
                "score": round(hit.get("distance", 0.0), 4),
                "content": entity.get("content", ""),
                "agent_name": entity.get("agent_name", ""),
                "tags": entity.get("tags", ""),
                "created_at": entity.get("created_at", ""),
            }
        )

    return json.dumps({"results": hits, "count": len(hits)})


@mcp.tool()
def memory_delete(memory_id: str, collection: Optional[str] = None) -> str:
    """Delete a memory by its ID.

    Args:
        memory_id: The UUID of the memory to delete.
        collection: Optional collection name. Defaults to "memory".
    """
    col = _full_collection_name(collection or DEFAULT_COLLECTION)
    _ensure_collection(col)
    client = _get_client()
    client.delete(
        collection_name=col,
        ids=[memory_id],
    )
    return json.dumps({"status": "deleted", "id": memory_id})


@mcp.tool()
def memory_list(
    collection: Optional[str] = None,
    agent_name: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> str:
    """List stored memories.

    Args:
        collection: Optional collection name to list from. Defaults to "memory".
        agent_name: Optional filter to only list memories from this agent.
        limit: Maximum number of results to return (default 20).
        offset: Number of results to skip for pagination (default 0).
    """
    col = _full_collection_name(collection or DEFAULT_COLLECTION)
    _ensure_collection(col)
    client = _get_client()

    filter_expr = f'agent_name == "{agent_name}"' if agent_name else ""

    results = client.query(
        collection_name=col,
        filter=filter_expr if filter_expr else None,
        output_fields=["content", "agent_name", "tags", "created_at"],
        limit=limit,
        offset=offset,
    )

    items = []
    for row in results:
        items.append(
            {
                "id": row.get("id", ""),
                "content": row.get("content", ""),
                "agent_name": row.get("agent_name", ""),
                "tags": row.get("tags", ""),
                "created_at": row.get("created_at", ""),
            }
        )

    return json.dumps({"results": items, "count": len(items)})


@mcp.tool()
def memory_collections() -> str:
    """List all memory collections."""
    client = _get_client()
    all_collections = client.list_collections()
    # Only return ezagent-prefixed collections, stripped of the prefix
    names = [
        c[len(COLLECTION_PREFIX):]
        for c in all_collections
        if c.startswith(COLLECTION_PREFIX)
    ]
    return json.dumps({"collections": sorted(names)})


if __name__ == "__main__":
    mcp.run()
