"""Load an isolated 100K-source-chunk retrieval benchmark generation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg

from bench.t12_corpus import CorpusFile, corpus_files, provenance, write_manifest
from reposcope.adapters.embedding import _mock_vector
from reposcope.domain.indexing import embedding_input


def validated_database_url(environment: Mapping[str, str]) -> str:
    """Allow destructive bulk loading only into an explicit disposable loopback DB."""
    if environment.get("T12_DISPOSABLE_DATABASE") != "1":
        raise ValueError("T12 requires explicit disposable database opt-in")
    url = environment.get("T12_DATABASE_URL", "")
    try:
        parsed = urlsplit(url)
        valid = (
            parsed.scheme == "postgresql"
            and parsed.hostname == "127.0.0.1"
            and parsed.port == 15432
            and parsed.username == "reposcope_migrator"
            and parsed.password is None
            and parsed.path == "/reposcope"
        )
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("T12 loader requires the isolated loopback database on port 15432")
    return url


def load(
    conn: psycopg.Connection[tuple[object, ...]],
    files: list[CorpusFile],
    *,
    baseline_index: bool = False,
) -> dict[str, object]:
    """Create one clearly labeled synthetic scope containing distinct public code files."""
    existing = conn.execute(
        "SELECT (SELECT count(*) FROM reposcope.repositories),"
        "(SELECT count(*) FROM reposcope.index_chunks)"
    ).fetchone()
    if existing != (0, 0):
        raise ValueError("T12 loader requires an empty disposable database")
    details = provenance(files)
    fingerprint = str(details["source_fingerprint"])
    principal_id, repository_id, generation_id = uuid4(), uuid4(), uuid4()
    commit_sha = fingerprint[:40]
    started = time.perf_counter()
    with conn.transaction():
        conn.execute(
            "INSERT INTO reposcope.repositories(repository_id,principal_id,url,created_at) "
            "VALUES(%s,%s,%s,clock_timestamp())",
            (
                repository_id,
                principal_id,
                "https://github.com/benchmark/t12-composite-public-source",
            ),
        )
        conn.execute(
            "INSERT INTO reposcope.source_revisions"
            "(repository_id,principal_id,commit_sha,created_at) "
            "VALUES(%s,%s,%s,clock_timestamp())",
            (repository_id, principal_id, commit_sha),
        )
        conn.execute(
            "INSERT INTO reposcope.index_generations(generation_id,repository_id,principal_id,"
            "requested_ref,commit_sha,status,embedding_space_version,created_at,updated_at) "
            "VALUES(%s,%s,%s,'t12-composite',%s,'ready',%s,clock_timestamp(),clock_timestamp())",
            (generation_id, repository_id, principal_id, commit_sha, "mock-sha256-384-l2-v1"),
        )
        conn.execute(
            "UPDATE reposcope.repositories SET active_generation_id=%s WHERE repository_id=%s",
            (generation_id, repository_id),
        )
    conn.execute("DROP INDEX reposcope.index_chunks_vector")
    conn.execute("DROP INDEX reposcope.index_chunks_fts")
    with conn.transaction():
        with conn.cursor().copy(
            "COPY reposcope.index_files(generation_id,path,content_sha256,byte_count,"
            "language,parse_mode,pipeline_version,dependencies,chunk_count) FROM STDIN"
        ) as copy:
            for file in files:
                copy.write_row(
                    (
                        generation_id,
                        file.path,
                        file.digest,
                        file.byte_count,
                        file.language,
                        file.parse_mode,
                        "t12-benchmark",
                        "[]",
                        len(file.chunks),
                    )
                )
    files_loaded_seconds = time.perf_counter() - started
    with conn.transaction():
        with conn.cursor().copy(
            "COPY reposcope.index_chunks(generation_id,path,ordinal,start_byte,end_byte,"
            "start_line,end_line,content_sha256,token_count,symbol,chunk_text,embedding) FROM STDIN"
        ) as copy:
            for file in files:
                for item in file.chunks:
                    chunk = item.chunk
                    raw = _mock_vector(embedding_input(chunk))
                    magnitude = sum(value * value for value in raw) ** 0.5
                    vector = "[" + ",".join(f"{value / magnitude:.7g}" for value in raw) + "]"
                    copy.write_row(
                        (
                            generation_id,
                            file.path,
                            chunk.ordinal,
                            chunk.start_byte,
                            chunk.end_byte,
                            chunk.start_line,
                            chunk.end_line,
                            chunk.sha256,
                            chunk.token_count,
                            chunk.symbol,
                            chunk.text,
                            vector,
                        )
                    )
    copy_seconds = time.perf_counter() - started
    conn.execute("SET maintenance_work_mem='1GB'")
    index_sql = (
        "CREATE INDEX index_chunks_vector ON reposcope.index_chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )
    if not baseline_index:
        index_sql += " WITH (m=64,ef_construction=400)"
    conn.execute(index_sql)
    hnsw_seconds = time.perf_counter() - started - copy_seconds
    conn.execute(
        "CREATE INDEX index_chunks_fts ON reposcope.index_chunks "
        "USING gin (to_tsvector('simple', chunk_text))"
    )
    conn.execute("ANALYZE reposcope.index_chunks")
    row = conn.execute(
        "SELECT count(*) FROM reposcope.index_chunks WHERE generation_id=%s", (generation_id,)
    ).fetchone()
    if row is None or row[0] != details["chunks"]:
        raise RuntimeError("Loaded chunk count does not match source manifest")
    return {
        **details,
        "principal_id": str(principal_id),
        "repository_id": str(repository_id),
        "generation_id": str(generation_id),
        "commit_sha": commit_sha,
        "files_loaded_seconds": round(files_loaded_seconds, 3),
        "copy_seconds": round(copy_seconds, 3),
        "hnsw_seconds": round(hnsw_seconds, 3),
        "total_load_seconds": round(time.perf_counter() - started, 3),
        "hnsw_index": "m=16,ef_construction=64" if baseline_index else "m=64,ef_construction=400",
    }


def main() -> None:
    """Read explicit local source paths and an isolated database URL from the environment."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--baseline-index", action="store_true")
    arguments = parser.parse_args()
    url = validated_database_url(os.environ)
    lib = Path(os.environ["T12_PYTHON_LIB"])
    packages = Path(os.environ["T12_SITE_PACKAGES"])
    tools = Path(os.environ["T12_PYTHON_TOOLS"])
    files = list(corpus_files(lib, packages, tools))
    write_manifest(arguments.manifest, files)
    with psycopg.connect(url, autocommit=True) as conn:
        result = load(conn, files, baseline_index=arguments.baseline_index)
    result["manifest_sha256"] = hashlib.sha256(arguments.manifest.read_bytes()).hexdigest()
    arguments.result.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({key: result[key] for key in ("files", "chunks", "total_load_seconds")}))


if __name__ == "__main__":
    main()
