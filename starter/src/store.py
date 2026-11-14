"""PostgreSQL + pgvector store. Exact cosine search (no ANN index: a few
hundred chunks), metadata filters in SQL with whitelisted keys and bound
parameters, idempotent upsert keyed by deterministic chunk_id."""
from __future__ import annotations

import json
from typing import Any

import psycopg

from .models import Chunk

FILTER_COLUMNS = {"chapter": "chapter", "article": "article", "page": "page",
                  "section": "section", "document_id": "document_id"}


def _vec(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.7f}" for x in v) + "]"


class PgVectorStore:
    def __init__(self, database_url: str, dimensions: int, model_name: str, table: str = "chunks") -> None:
        if dimensions <= 0:
            raise ValueError("dimensions must be positive")
        self.url, self.dim, self.model, self.table = database_url, dimensions, model_name, table
        # autocommit: each upsert() runs in its own explicit transaction block
        self.conn = psycopg.connect(database_url, connect_timeout=5, autocommit=True)

    def versions(self) -> dict:
        with self.conn.cursor() as cur:
            cur.execute("SELECT current_setting('server_version'), "
                        "(SELECT extversion FROM pg_extension WHERE extname='vector')")
            pg, vec = cur.fetchone()
        return {"postgres": pg, "pgvector": vec, "table": self.table, "metric": "cosine (<=>)",
                "search": "exact (sequential scan, no ANN index)"}

    def create_schema(self) -> None:
        t = self.table
        with self.conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS {t} (
                    chunk_id        text PRIMARY KEY,
                    strategy        text NOT NULL,
                    document_id     text NOT NULL,
                    source          text NOT NULL,
                    page            integer NOT NULL,
                    chapter         text,
                    chapter_title   text,
                    section         text,
                    article         integer,
                    text            text NOT NULL,
                    content_hash    text NOT NULL,
                    char_count      integer NOT NULL,
                    metadata        jsonb NOT NULL DEFAULT '{{}}',
                    embedding_model text NOT NULL,
                    embedding       vector({self.dim}) NOT NULL,
                    updated_at      timestamptz NOT NULL DEFAULT now()
                )""")
            cur.execute(f"CREATE INDEX IF NOT EXISTS {t}_strategy_idx ON {t} (strategy, document_id)")
            cur.execute(f"CREATE INDEX IF NOT EXISTS {t}_chapter_idx ON {t} (strategy, chapter)")
            cur.execute("SELECT atttypmod FROM pg_attribute WHERE attrelid = %s::regclass AND attname = 'embedding'", (t,))
            (typmod,) = cur.fetchone()
        if typmod != self.dim:
            raise RuntimeError(f"Table {t} has vector({typmod}) but model gives {self.dim} dims; "
                               "use another table or drop it deliberately.")

    def existing(self, strategy: str) -> dict[str, tuple[str, str]]:
        with self.conn.cursor() as cur:
            cur.execute(f"SELECT chunk_id, content_hash, embedding_model FROM {self.table} WHERE strategy = %s", (strategy,))
            return {r[0]: (r[1], r[2]) for r in cur.fetchall()}

    def upsert(self, strategy: str, chunks: list[Chunk], vectors: list[list[float]] | None,
               all_chunk_ids: list[str], document_ids: list[str]) -> dict[str, int]:
        """Write new/changed chunks, then delete chunks of these documents that
        no longer exist (obsolete after a source change). `chunks`/`vectors`
        only contain new or changed chunks; `all_chunk_ids` is the full current set."""
        vectors = vectors or []
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors differ in length")
        if any(len(v) != self.dim for v in vectors):
            raise ValueError("vector dimension mismatch")
        if len(set(all_chunk_ids)) != len(all_chunk_ids):
            raise ValueError("duplicate chunk ids in input")
        inserted = updated = 0
        with self.conn.transaction(), self.conn.cursor() as cur:
            for c, v in zip(chunks, vectors):
                m = c.metadata
                cur.execute(f"""
                    INSERT INTO {self.table} (chunk_id, strategy, document_id, source, page, chapter,
                        chapter_title, section, article, text, content_hash, char_count, metadata,
                        embedding_model, embedding)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector)
                    ON CONFLICT (chunk_id) DO UPDATE SET
                        text = EXCLUDED.text, content_hash = EXCLUDED.content_hash,
                        char_count = EXCLUDED.char_count, metadata = EXCLUDED.metadata,
                        page = EXCLUDED.page, chapter = EXCLUDED.chapter,
                        chapter_title = EXCLUDED.chapter_title, section = EXCLUDED.section,
                        article = EXCLUDED.article, embedding_model = EXCLUDED.embedding_model,
                        embedding = EXCLUDED.embedding, updated_at = now()
                    RETURNING (xmax = 0)""",
                    (c.chunk_id, strategy, c.document_id, c.source, c.page, m.get("chapter"),
                     m.get("chapter_title"), m.get("section"), m.get("article"), c.text,
                     m["content_hash"], m["char_count"], json.dumps(m, ensure_ascii=False),
                     self.model, _vec(v)))
                if cur.fetchone()[0]:
                    inserted += 1
                else:
                    updated += 1
            cur.execute(f"DELETE FROM {self.table} WHERE strategy = %s AND document_id = ANY(%s) "
                        f"AND NOT (chunk_id = ANY(%s))", (strategy, document_ids, all_chunk_ids))
            deleted = cur.rowcount
        return {"inserted": inserted, "updated": updated, "deleted": deleted,
                "unchanged": len(all_chunk_ids) - inserted - updated}

    def stats(self, strategy: str) -> dict[str, int]:
        with self.conn.cursor() as cur:
            cur.execute(f"""SELECT count(*), count(DISTINCT chunk_id),
                            count(*) - count(DISTINCT (page, content_hash))
                            FROM {self.table} WHERE strategy = %s""", (strategy,))
            n, ids, dup = cur.fetchone()
        return {"rows": n, "distinct_ids": ids, "duplicate_text_same_page": dup}

    def search(self, strategy: str, query_vector: list[float], top_k: int = 3,
               filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if len(query_vector) != self.dim:
            raise ValueError("query vector dimension mismatch")
        where, params = ["strategy = %s"], [strategy]
        for key, value in (filters or {}).items():
            if key not in FILTER_COLUMNS:
                raise ValueError(f"filter key not allowed: {key}")
            where.append(f"{FILTER_COLUMNS[key]} = %s")
            params.append(value)
        q = _vec(query_vector)
        sql = (f"SELECT chunk_id, document_id, source, page, chapter, chapter_title, section, article, "
               f"text, metadata, 1 - (embedding <=> %s::vector) AS score FROM {self.table} "
               f"WHERE {' AND '.join(where)} ORDER BY embedding <=> %s::vector LIMIT %s")
        with self.conn.cursor() as cur:
            cur.execute(sql, [q, *params, q, top_k])
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
