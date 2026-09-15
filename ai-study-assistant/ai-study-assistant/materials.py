"""
Retrieval-Augmented Generation layer.

Every uploaded document is split into overlapping word-chunks and stored in
SQLite. At query time we fit a TF-IDF vectorizer over the *current session's*
chunks and rank them by cosine similarity to the question -- classic sparse
RAG. It needs no embeddings API and no GPU, so the "R" in RAG works even with
no LLM key configured at all.
"""

import re
import uuid
from datetime import datetime, timezone

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from db import get_conn

CHUNK_SIZE_WORDS = 180
CHUNK_OVERLAP_WORDS = 40


def _chunk_text(text):
    words = re.sub(r"\s+", " ", text).strip().split(" ")
    if not words or words == [""]:
        return []

    chunks = []
    start = 0
    while start < len(words):
        end = min(start + CHUNK_SIZE_WORDS, len(words))
        chunk = " ".join(words[start:end]).strip()
        if chunk:
            chunks.append(chunk)
        if end == len(words):
            break
        start = end - CHUNK_OVERLAP_WORDS
    return chunks


def save_material(session_id, title, text):
    material_id = uuid.uuid4().hex[:12]
    created_at = datetime.now(timezone.utc).isoformat()
    chunks = _chunk_text(text)

    conn = get_conn()
    conn.execute(
        "INSERT INTO materials (id, session_id, title, created_at) VALUES (?, ?, ?, ?)",
        (material_id, session_id, title, created_at),
    )
    conn.executemany(
        "INSERT INTO chunks (material_id, session_id, chunk_index, content) VALUES (?, ?, ?, ?)",
        [(material_id, session_id, i, c) for i, c in enumerate(chunks)],
    )
    conn.commit()
    conn.close()

    return {
        "id": material_id,
        "title": title,
        "created_at": created_at,
        "chunk_count": len(chunks),
    }


def list_materials(session_id):
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT m.id, m.title, m.created_at, COUNT(c.id) AS chunk_count
        FROM materials m LEFT JOIN chunks c ON c.material_id = m.id
        WHERE m.session_id = ?
        GROUP BY m.id ORDER BY m.created_at DESC
        """,
        (session_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def delete_material(session_id, material_id):
    conn = get_conn()
    conn.execute("DELETE FROM chunks WHERE material_id = ? AND session_id = ?", (material_id, session_id))
    conn.execute("DELETE FROM materials WHERE id = ? AND session_id = ?", (material_id, session_id))
    conn.commit()
    conn.close()


def retrieve_chunks(session_id, query, top_k=4):
    """Return the top_k most relevant chunks (with source title) for a query."""
    conn = get_conn()
    rows = conn.execute(
        """
        SELECT c.content, m.title
        FROM chunks c JOIN materials m ON m.id = c.material_id
        WHERE c.session_id = ?
        """,
        (session_id,),
    ).fetchall()
    conn.close()

    if not rows:
        return []

    documents = [r["content"] for r in rows]
    titles = [r["title"] for r in rows]

    if len(documents) == 1:
        return [{"content": documents[0], "source": titles[0], "score": 1.0}]

    try:
        vectorizer = TfidfVectorizer(stop_words="english")
        matrix = vectorizer.fit_transform(documents + [query])
        similarities = cosine_similarity(matrix[-1], matrix[:-1]).flatten()
    except ValueError:
        # e.g. query is only stopwords -> fall back to most recent chunks
        return [
            {"content": d, "source": t, "score": 0.0}
            for d, t in list(zip(documents, titles))[-top_k:]
        ]

    ranked = sorted(zip(similarities, documents, titles), key=lambda x: x[0], reverse=True)
    results = [
        {"content": d, "source": t, "score": round(float(s), 4)}
        for s, d, t in ranked[:top_k]
        if s > 0
    ]
    return results or [
        {"content": d, "source": t, "score": 0.0} for d, t in list(zip(documents, titles))[:top_k]
    ]
