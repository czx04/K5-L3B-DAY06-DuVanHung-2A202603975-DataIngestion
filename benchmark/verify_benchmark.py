"""Check the benchmark before any retrieval run.

python benchmark/verify_benchmark.py   (from repo root)
- every evidence_quote occurs verbatim in the normalized text of gold_page
- the quote does not occur on any other counted page (unique gold)
- filter values exist in page metadata and match the gold page's chapter
- split sizes and filter coverage meet BENCHMARK.md
"""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
pages = {p["page"]: p for p in map(json.loads, open(ROOT / "data/processed/pages.jsonl", encoding="utf-8"))}
questions = json.load(open(ROOT / "benchmark/questions.json", encoding="utf-8"))
chapters = {c for p in pages.values() for c in [p["metadata"]["chapter_at_start"], p["metadata"]["chapter_at_end"], *p["metadata"]["chapters_on_page"]] if c}
REQUIRED = ["id", "split", "question", "expected_answer", "gold_source_id", "gold_page", "evidence_quote", "filter"]

errors, rows = [], []
for q in questions:
    missing = [k for k in REQUIRED if k not in q]
    if missing:
        errors.append(f"{q.get('id')}: missing {missing}")
        continue
    page = pages.get(q["gold_page"])
    ok_gold = bool(page and page["metadata"]["counted"] and q["evidence_quote"] in page["text"])
    others = [n for n, p in pages.items() if n != q["gold_page"] and p["metadata"]["counted"] and q["evidence_quote"] in p["text"]]
    ok_filter = True
    if q["filter"]:
        ch = q["filter"].get("chapter")
        gold_chs = {page["metadata"]["chapter_at_start"], page["metadata"]["chapter_at_end"], *page["metadata"]["chapters_on_page"]} if page else set()
        ok_filter = ch in chapters and ch in gold_chs
    if not ok_gold:
        errors.append(f"{q['id']}: evidence not found on gold page {q['gold_page']}")
    if others:
        errors.append(f"{q['id']}: evidence also on pages {others}")
    if not ok_filter:
        errors.append(f"{q['id']}: filter {q['filter']} invalid for gold page")
    rows.append((q["id"], q["split"], q.get("type"), q["gold_page"], q["filter"], ok_gold and not others and ok_filter))

for r in rows:
    print(f"{r[0]} {r[1]:4} {str(r[2]):16} page={r[3]:<3} filter={r[4]} {'OK' if r[5] else 'FAIL'}")
split = Counter(q["split"] for q in questions)
filt = Counter(q["split"] for q in questions if q["filter"])
print(f"\nsplit={dict(split)} filter_questions={dict(filt)} types={dict(Counter(q.get('type') for q in questions))}")
if split["dev"] < 15 or split["test"] < 5:
    errors.append("need >=15 dev and >=5 test")
if sum(filt.values()) < 3 or filt["test"] < 1:
    errors.append("need >=3 filter questions with >=1 in test")
if errors:
    print("\n".join(["ERRORS:"] + errors))
    sys.exit(1)
print("Benchmark OK")
