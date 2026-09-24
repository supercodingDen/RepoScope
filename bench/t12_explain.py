"""Capture the actual scoped retrieval plans without source text or credentials."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from uuid import UUID

import psycopg

from bench.t12_measure import query_vector
from reposcope.adapters.postgres_retrieval import _FILTER, _parameters
from reposcope.domain.retrieval import RetrievalScope


def main() -> None:
    """Explain the production-shaped vector and lexical SQL on an isolated scope."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--loaded", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    data = json.loads(arguments.manifest.read_text(encoding="utf-8"))
    loaded = json.loads(arguments.loaded.read_text(encoding="utf-8"))
    query: str = data["queries"][0]["query"]
    scope = RetrievalScope(
        UUID(loaded["repository_id"]),
        UUID(loaded["generation_id"]),
        loaded["commit_sha"],
        "mock-sha256-384-l2-v1",
        loaded["chunks"],
    )
    filters = _parameters(scope, None, None)
    fields = "c.path,c.ordinal,c.start_line,c.end_line,c.chunk_text,f.language"
    vector_sql = (
        "SELECT "
        + fields
        + " "
        + _FILTER
        + "ORDER BY c.embedding <=> %s::vector,c.path,c.ordinal LIMIT 50"
    )
    lexical_sql = (
        "SELECT "
        + fields
        + " "
        + _FILTER
        + "AND to_tsvector('simple',c.chunk_text) @@ plainto_tsquery('simple',%s) "
        "ORDER BY ts_rank_cd(to_tsvector('simple',c.chunk_text),"
        "plainto_tsquery('simple',%s)) DESC,c.path,c.ordinal LIMIT 50"
    )
    with psycopg.connect(os.environ["T12_DATABASE_URL"], autocommit=True) as conn:
        conn.execute("SET hnsw.ef_search=400")
        conn.execute("SET hnsw.iterative_scan='strict_order'")
        plans: dict[str, object] = {}
        for name, statement, params in (
            ("vector", vector_sql, (*filters, query_vector(query))),
            ("lexical", lexical_sql, (*filters, query, query)),
        ):
            cursor = conn.execute("EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) " + statement, params)
            row = cursor.fetchone()
            if row is None:
                raise RuntimeError("EXPLAIN returned no plan")
            plans[name] = row[0]
            count = conn.execute(statement, params).fetchall()
            plans[name + "_rows"] = len(count)
    arguments.output.write_text(json.dumps(plans, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in plans.items() if key.endswith("_rows")}))


if __name__ == "__main__":
    main()
