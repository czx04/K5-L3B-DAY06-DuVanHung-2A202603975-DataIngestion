"""Day 06 pipeline entry point (run from starter/).

  python -m src.ingest                      # step 1: PDF -> data/processed/pages.jsonl
  python -m src.run index                   # step 2: chunk A/B, embed, store, re-ingest check
  python -m src.run query "câu hỏi" -s C --chapter X   # smoke test
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from .chunking import build_chunks
from .config import PAGES_FILE, RESULTS, STRATEGIES, TOP_K
from .embeddings import get_embedder
from .models import DocumentPage
from .store import PgVectorStore

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def load_pages() -> list[DocumentPage]:
    if not PAGES_FILE.exists():
        raise SystemExit("Run `python -m src.ingest` first")
    pages = [DocumentPage(**json.loads(l)) for l in open(PAGES_FILE, encoding="utf-8")]
    counted = [p for p in pages if p.metadata["counted"]]
    if len(counted) < 30:
        raise SystemExit(f"only {len(counted)} content pages")
    return counted


def open_store(embedder) -> PgVectorStore:
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL missing in starter/.env")
    store = PgVectorStore(url, embedder.dimensions, embedder.model_name)
    store.create_schema()
    return store


def length_stats(lengths: list[int]) -> dict:
    q = statistics.quantiles(lengths, n=4)
    return {"min": min(lengths), "p25": q[0], "median": q[1], "p75": q[2], "max": max(lengths),
            "mean": round(sum(lengths) / len(lengths), 1), "total_chars": sum(lengths)}


def index_strategy(name: str, pages, embedder, store) -> dict:
    cfg = STRATEGIES[name]
    t0 = time.perf_counter()
    chunks = build_chunks(pages, name, cfg["params"])
    t_chunk = time.perf_counter() - t0
    existing = store.existing(name)
    todo = [c for c in chunks
            if existing.get(c.chunk_id) != (c.metadata["content_hash"], embedder.model_name)]
    t1 = time.perf_counter()
    vectors = embedder.embed_documents([c.text for c in todo]) if todo else []
    t_embed = time.perf_counter() - t1
    t2 = time.perf_counter()
    result = store.upsert(name, todo, vectors, [c.chunk_id for c in chunks],
                          sorted({c.document_id for c in chunks}))
    t_store = time.perf_counter() - t2
    with open(RESULTS / f"chunks_{name}.jsonl", "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(asdict(c), ensure_ascii=False) + "\n")
    tok_lens = embedder.token_lengths([c.text for c in chunks]) if hasattr(embedder, "token_lengths") else None
    limit = getattr(embedder, "max_seq_length", None)
    return {"strategy_index": name, "params": cfg["params"], "chunk_count": len(chunks),
            "length_chars": length_stats([len(c.text) for c in chunks]),
            "tokens_model": ({**{k.replace("total_chars", "total"): v for k, v in length_stats(tok_lens).items()},
                              "max_seq_length": limit,
                              "chunks_truncated": sum(1 for n in tok_lens if limit and n > limit)}
                             if tok_lens else None),
            "embedded_now": len(todo), "upsert": result,
            "seconds": {"chunking": round(t_chunk, 2), "embedding": round(t_embed, 2),
                        "store": round(t_store, 2), "total": round(t_chunk + t_embed + t_store, 2)},
            "db": store.stats(name)}


def cmd_index(_args) -> None:
    RESULTS.mkdir(exist_ok=True)
    pages = load_pages()
    t0 = time.perf_counter()
    embedder = get_embedder()
    t_model = time.perf_counter() - t0
    store = open_store(embedder)
    run = {"run_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "embedding": embedder.info(), "vector_store": store.versions(),
           "model_load_seconds": round(t_model, 2), "content_pages": len(pages),
           "strategies": {k: {kk: vv for kk, vv in v.items()} for k, v in STRATEGIES.items()},
           "first_ingest": {}, "reingest_check": {}}
    for name in sorted({s["index"] for s in STRATEGIES.values()}):
        run["first_ingest"][name] = index_strategy(name, pages, embedder, store)
        print(name, json.dumps(run["first_ingest"][name]["upsert"]), run["first_ingest"][name]["seconds"])
    # Re-ingest the same version: must insert/update/delete nothing, no duplicates.
    for name in run["first_ingest"]:
        r = index_strategy(name, pages, embedder, store)
        ok = (r["upsert"]["inserted"] == r["upsert"]["updated"] == r["upsert"]["deleted"] == 0
              and r["db"]["rows"] == r["chunk_count"] and r["db"]["duplicate_text_same_page"] == 0)
        run["reingest_check"][name] = {"upsert": r["upsert"], "db": r["db"], "passed": ok}
        print(f"reingest {name}: {'PASS' if ok else 'FAIL'} {r['upsert']} {r['db']}")
    run["embedding"] = embedder.info()
    (RESULTS / "index_run.json").write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
    print("-> results/index_run.json, results/chunks_A.jsonl, results/chunks_B.jsonl")


def cmd_query(args) -> None:
    embedder = get_embedder()
    store = open_store(embedder)
    cfg = STRATEGIES[args.strategy]
    filters = {"chapter": args.chapter} if (args.chapter and cfg["use_filter"]) else None
    for h in store.search(cfg["index"], embedder.embed_query(args.question), TOP_K, filters):
        print(f"{h['score']:.4f} p{h['page']} ch{h['chapter']} Đ{h['article']} {h['chunk_id']}\n   {h['text'][:200]!r}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("index")
    q = sub.add_parser("query")
    q.add_argument("question")
    q.add_argument("-s", "--strategy", default="B", choices=list(STRATEGIES))
    q.add_argument("--chapter")
    args = ap.parse_args()
    {"index": cmd_index, "query": cmd_query}[args.cmd](args)


if __name__ == "__main__":
    main()
