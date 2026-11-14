"""Manual audit sheets (filled by the author, not by code) and their summary.

Sheets are written to results/audit/*.csv (UTF-8 with BOM, opens in Excel/Numbers).
Fill the columns marked `label_*` / `reason`, save as CSV, then run audit-summary.
Columns prefixed `auto_` are mechanical helper checks, not labels.
"""
from __future__ import annotations

import csv
import json
import re
from collections import Counter, defaultdict

from .config import PAGES_FILE, RESULTS, STRATEGIES

AUDIT = RESULTS / "audit"
N_POSITIONS = 10


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def _strip_prefix(text: str) -> str:
    # B chunks may start with "Điều N. ... (tiếp)\n" added by the chunker
    return re.sub(r"^Điều \d+\..*\(tiếp\)\n", "", text)


def _write(path, rows, fields):
    AUDIT.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def _read(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _chunks(index: str) -> list[dict]:
    return [json.loads(l) for l in open(RESULTS / f"chunks_{index}.jsonl", encoding="utf-8")]


def coherence_positions(pages: list[dict]) -> list[dict]:
    """Rule fixed independently of scores: 10 pages evenly spread over the
    counted pages; position = start of the paragraph containing the page midpoint."""
    counted = [p for p in pages if p["metadata"]["counted"]]
    picks = [counted[round(i * (len(counted) - 1) / (N_POSITIONS - 1))] for i in range(N_POSITIONS)]
    out = []
    for i, p in enumerate(picks, 1):
        text, mid = p["text"], len(p["text"]) // 2
        start = text.rfind("\n", 0, mid) + 1
        anchor = text[start:start + 60].split("\n")[0]
        out.append({"position_id": f"pos{i:02d}", "page": p["page"], "char_offset": start, "anchor": anchor})
    return out


def _chunk_for(pos: dict, chunks: list[dict], index: str) -> dict | None:
    same = [c for c in chunks if c["page"] == pos["page"]]
    if index == "A":  # window that contains the anchor offset (latest start)
        cand = [c for c in same if c["metadata"]["char_start"] <= pos["char_offset"]
                < c["metadata"]["char_start"] + 500]
        return cand[-1] if cand else None
    for c in same:
        if pos["anchor"][:40] in c["text"]:
            return c
    return None


def cmd_audit(_args) -> None:
    pages = {p["page"]: p for p in map(json.loads, open(PAGES_FILE, encoding="utf-8"))}
    # 1) coherence: same 10 positions for each chunk set (C uses B's chunks)
    positions = coherence_positions(list(pages.values()))
    rows = []
    for index in ("A", "B"):
        chunks = _chunks(index)
        for pos in positions:
            c = _chunk_for(pos, chunks, index)
            rows.append({"position_id": pos["position_id"], "page": pos["page"], "anchor": pos["anchor"],
                         "strategy": index + (" (= C)" if index == "B" else ""),
                         "chunk_id": c["chunk_id"] if c else "", "chunk_text": c["text"] if c else "",
                         "label_0_1_2": "", "reason": ""})
    _write(AUDIT / "coherence_sheet.csv", rows,
           ["position_id", "page", "anchor", "strategy", "chunk_id", "chunk_text", "label_0_1_2", "reason"])
    (AUDIT / "coherence_positions.json").write_text(json.dumps(
        {"rule": coherence_positions.__doc__.strip(), "positions": positions}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    # 2) metadata + 3) grounding from TEST traces
    tr = {n: [json.loads(l) for l in open(RESULTS / "traces" / f"test_{n}.jsonl", encoding="utf-8")]
          for n in STRATEGIES}
    meta_rows, ground_rows = [], []
    for n, traces in tr.items():
        for t in traces:
            for r in t["results"]:
                pg = pages[r["page"]]
                chs = {pg["metadata"]["chapter_at_start"], pg["metadata"]["chapter_at_end"],
                       *pg["metadata"]["chapters_on_page"]}
                meta_rows.append({
                    "strategy": n, "id": t["id"], "rank": r["rank"], "chunk_id": r["chunk_id"],
                    "source": r["source"], "page": r["page"], "chapter": r["chapter"], "article": r["article"],
                    "question_filter": json.dumps(t["question_filter"], ensure_ascii=False) if t["question_filter"] else "",
                    "auto_text_on_page": _norm(_strip_prefix(r["text"])) in _norm(pg["text"]),
                    "auto_chapter_on_page": r["chapter"] in chs,
                    "chunk_text": r["text"], "label_metadata_correct_1_0": "", "reason": ""})
            top = "\n\n".join(f"[{r['rank']}] p{r['page']} Đ{r['article']} (score {r['score']}):\n{r['text']}"
                              for r in t["results"])
            ground_rows.append({"strategy": n, "id": t["id"], "question": t["question"],
                                "filter_applied": json.dumps(t["filter_applied"], ensure_ascii=False) if t["filter_applied"] else "",
                                "expected_answer": next(q["expected_answer"] for q in json.load(open(
                                    RESULTS.parent / "benchmark/questions.json", encoding="utf-8")) if q["id"] == t["id"]),
                                "evidence_quote": t["evidence_quote"], "gold_page": t["gold_page"],
                                "auto_evidence_hit3": t["hit_at_3"], "top3": top,
                                "label_0_1_2": "", "reason": ""})
    _write(AUDIT / "metadata_sheet.csv", meta_rows, list(meta_rows[0]))
    _write(AUDIT / "grounding_sheet.csv", ground_rows, list(ground_rows[0]))
    print(f"-> {AUDIT}/coherence_sheet.csv ({len(rows)} rows), metadata_sheet.csv ({len(meta_rows)}), "
          f"grounding_sheet.csv ({len(ground_rows)})")
    print("Thang: coherence 0=cắt giữa ý/không hiểu, 1=hiểu một phần, 2=tự hiểu, trọn ý; "
          "grounding 0=không có bằng chứng, 1=có nhưng thiếu điều kiện/ngữ cảnh, 2=đủ để trả lời và truy nguồn; "
          "metadata 1=source/page/chapter/article đủ và đúng so với PDF, 0=sai/thiếu (ghi lỗi).")


def cmd_audit_summary(_args) -> None:
    missing: list[str] = []
    out = ["# Audit thủ công — tổng hợp", "",
           "Quy trình chấm: nhãn và lý do do AI (Claude) đề xuất, tác giả đã đọc lại toàn bộ và chấp nhận "
           "không sửa ô nào (2026-11-14). Nguy cơ thiên lệch: tác giả cũng là người thiết kế pipeline; "
           "nhãn AI có thể bị neo theo kết quả tự động; chỉ một người duyệt, không đo độ đồng thuận.", ""]
    coh = _read(AUDIT / "coherence_sheet.csv")
    by = defaultdict(list)
    for r in coh:
        if r["label_0_1_2"].strip() == "":
            missing.append(f"coherence {r['position_id']} {r['strategy']}")
            continue
        by[r["strategy"].split()[0]].append(int(r["label_0_1_2"]))
    out += ["## Coherence (10 vị trí, thang 0–2; C dùng chung chunk với B)", "",
            "| Strategy | n | 0/1/2 | Trung bình /2 |", "|---|---|---|---|"]
    for n in ("A", "B"):
        v = by.get(n, [])
        c = Counter(v)
        out.append(f"| {n}{' (= C)' if n == 'B' else ''} | {len(v)} | {c[0]}/{c[1]}/{c[2]} | "
                   f"{(sum(v) / len(v)) if v else float('nan'):.2f} |")
    meta = _read(AUDIT / "metadata_sheet.csv")
    out += ["", "## Metadata (5 câu test × top-3)", "", "| Strategy | Đủ và đúng | Filter tuân thủ |", "|---|---|---|"]
    mtest = json.load(open(RESULTS / "metrics_test.json", encoding="utf-8"))["summary"]
    for n in STRATEGIES:
        rows = [r for r in meta if r["strategy"] == n]
        lab = [r for r in rows if r["label_metadata_correct_1_0"].strip() != ""]
        missing += [f"metadata {n} {r['id']} rank{r['rank']}" for r in rows if r not in lab]
        ok = sum(int(r["label_metadata_correct_1_0"]) for r in lab)
        out.append(f"| {n} | {ok}/{len(lab)} | {mtest[n]['test']['filter_compliance_str']} |")
    gr = _read(AUDIT / "grounding_sheet.csv")
    out += ["", "## Grounding (5 câu test, thang 0–2)", "", "| Strategy | 0/1/2 (số câu) | Trung bình /2 |", "|---|---|---|"]
    for n in STRATEGIES:
        v = [int(r["label_0_1_2"]) for r in gr if r["strategy"] == n and r["label_0_1_2"].strip() != ""]
        missing += [f"grounding {n} {r['id']}" for r in gr if r["strategy"] == n and r["label_0_1_2"].strip() == ""]
        c = Counter(v)
        out.append(f"| {n} | {c[0]}/{c[1]}/{c[2]} | {(sum(v) / len(v)) if v else float('nan'):.2f} |")
    if missing:
        out += ["", f"**Chưa chấm {len(missing)} ô:** " + "; ".join(missing[:20]) + (" …" if len(missing) > 20 else "")]
    (RESULTS / "audit_summary.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))
