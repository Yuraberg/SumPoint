"""Duplicate grouping via BGE-M3 embedding cosine similarity.

The same story reposted across several channels produces near-identical
embeddings. Each post is assigned a ``cluster_id`` — the id of the cluster's
representative (earliest) post — so the feed can show "также в N каналах" on one
row instead of repeating the story.

Assignment is deliberately incremental and cheap: a new post runs a single
pgvector nearest-neighbour query, scoped to the same user's channels within a
short time window, and adopts the neighbour's cluster if close enough. It never
re-clusters existing posts, so ingestion cost stays O(1) per post.

Graceful degradation: when BGE-M3 (Ollama) is unavailable, ``generate_embedding``
falls back to a zero vector. Two zero vectors have cosine distance 0, so naive
clustering would falsely merge every embedding-less post. We guard against that
by treating a missing/zero embedding as *unclusterable* — those posts get
``cluster_id = NULL`` (or their own id for backfill callers) and never pull
others in. The service therefore degrades to "no grouping" instead of breaking.
"""
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.post import Post


def is_usable_embedding(embedding) -> bool:
    """True only for a real, non-zero vector. A None or all-zeros embedding is
    the Ollama-down fallback and must not participate in clustering."""
    if embedding is None:
        return False
    try:
        return any(float(x) != 0.0 for x in embedding)
    except TypeError:
        return False


def _vec_literal(embedding) -> str:
    return "[" + ",".join(str(float(x)) for x in embedding) + "]"


async def _nearest_cluster(
    db: AsyncSession,
    user_id: int,
    embedding,
    self_id: int,
    lo,
    hi,
    max_distance: float,
) -> int | None:
    """cluster_id of the closest already-clustered post within the window and
    distance bound, or None if nothing qualifies."""
    sql = text(
        """
        SELECT p.cluster_id
        FROM posts p
        JOIN channels c ON c.id = p.channel_id
        WHERE c.user_id = :uid
          AND p.id <> :self_id
          AND p.embedding IS NOT NULL
          AND p.cluster_id IS NOT NULL
          AND p.published_at >= :lo
          AND p.published_at <= :hi
          AND (p.embedding <=> CAST(:vec AS vector)) <= :max_dist
        ORDER BY p.embedding <=> CAST(:vec AS vector)
        LIMIT 1
        """
    )
    row = (
        await db.execute(
            sql,
            {
                "uid": user_id,
                "self_id": self_id,
                "lo": lo,
                "hi": hi,
                "vec": _vec_literal(embedding),
                "max_dist": max_distance,
            },
        )
    ).first()
    return row.cluster_id if row else None


async def assign_cluster(db: AsyncSession, post: Post, user_id: int, *, flush: bool = True) -> None:
    """Set ``post.cluster_id`` in place. Assumes ``post.id`` is already
    populated (call after the insert has flushed). Caller commits."""
    settings = get_settings()
    if not settings.clustering_enabled:
        return

    if not is_usable_embedding(post.embedding):
        # Embedding-less post: singleton, and never a magnet for others.
        post.cluster_id = post.id
        if flush:
            await db.flush()
        return

    window = timedelta(days=settings.cluster_window_days)
    max_distance = 1.0 - settings.cluster_similarity_threshold
    neighbor_cluster = await _nearest_cluster(
        db,
        user_id,
        post.embedding,
        post.id,
        post.published_at - window,
        post.published_at + window,
        max_distance,
    )
    post.cluster_id = neighbor_cluster if neighbor_cluster is not None else post.id
    if flush:
        await db.flush()
