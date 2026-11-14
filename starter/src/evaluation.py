"""Automatic retrieval metrics + traces. Manual labels (coherence, grounding,
metadata correctness) are NOT inferred here; see src/audit.py for the sheets."""
from __future__ import annotations

import re
from typing import Any


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def is_hit(question: dict[str, Any], hit: dict[str, Any]) -> bool:
    """Hit = chunk from the gold source AND gold page AND contains the full evidence."""
    golds = question.get("alt_gold") or []
    golds = [{"source_id": question["gold_source_id"], "page": question["gold_page"],
              "evidence": question["evidence_quote"]}] + golds
    text = _norm(hit["text"])
    return any(hit["document_id"] == g["source_id"] and hit["page"] == g["page"]
               and _norm(g["evidence"]) in text for g in golds)


def evaluate_query(question: dict[str, Any], hits: list[dict[str, Any]], strategy: str,
                   filter_used: dict | None) -> dict[str, Any]:
    flags = [is_hit(question, h) for h in hits]
    on_gold_page = [h["page"] == question["gold_page"] for h in hits]
    # evidence split: gold page retrieved but no single chunk holds the whole quote
    split = any(on_gold_page) and not any(flags)
    filt = question.get("filter")
    compliance = None
    if filt:
        compliance = all(h.get("chapter") == filt["chapter"] for h in hits)
    return {
        "strategy": strategy, "id": question["id"], "split": question["split"],
        "type": question.get("type"), "question": question["question"],
        "question_filter": filt, "filter_applied": filter_used,
        "gold_page": question["gold_page"], "gold_article": question.get("gold_article"),
        "evidence_quote": question["evidence_quote"],
        "hit_at_1": bool(flags and flags[0]), "hit_at_3": any(flags),
        "first_hit_rank": (flags.index(True) + 1) if any(flags) else None,
        "gold_page_in_top3": any(on_gold_page), "evidence_split_or_partial": split,
        "top3_within_filter_chapter": compliance,
        "results": [{"rank": i + 1, "chunk_id": h["chunk_id"], "score": round(float(h["score"]), 4),
                     "document_id": h["document_id"], "source": h["source"], "page": h["page"],
                     "chapter": h["chapter"], "article": h["article"], "is_hit": f,
                     "text": h["text"]} for i, (h, f) in enumerate(zip(hits, flags))],
    }


def summarize(traces: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for t in traces:
        s = out.setdefault(t["strategy"], {}).setdefault(t["split"], {
            "n": 0, "hit_at_1": 0, "hit_at_3": 0, "evidence_split": 0,
            "filter_questions": 0, "filter_compliant": 0, "misses": []})
        s["n"] += 1
        s["hit_at_1"] += t["hit_at_1"]
        s["hit_at_3"] += t["hit_at_3"]
        s["evidence_split"] += t["evidence_split_or_partial"]
        if t["question_filter"]:
            s["filter_questions"] += 1
            s["filter_compliant"] += bool(t["top3_within_filter_chapter"])
        if not t["hit_at_3"]:
            s["misses"].append(t["id"])
    for strat in out.values():
        for s in strat.values():
            s["hit_at_1_str"] = f"{s['hit_at_1']}/{s['n']}"
            s["hit_at_3_str"] = f"{s['hit_at_3']}/{s['n']}"
            s["filter_compliance_str"] = (f"{s['filter_compliant']}/{s['filter_questions']}"
                                          if s["filter_questions"] else "N/A")
    return out
