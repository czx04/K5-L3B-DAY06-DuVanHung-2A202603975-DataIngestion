"""Step 1 of the pipeline: ingest the corpus and write manifest + processed pages.

Run from starter/:  python -m src.ingest
Outputs (repo root): data/manifest.json, data/processed/pages.jsonl,
                     results/ingestion_log.json
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict
from pathlib import Path

from pypdf import PdfReader

from .ingestion import load_pdf

ROOT = Path(__file__).resolve().parents[2]
STARTER = ROOT / "starter"

SOURCES = [
    {
        "source_id": "blld-vbhn-125-2025",
        "title": "Bộ luật Lao động (Văn bản hợp nhất số 125/VBHN-VPQH năm 2025)",
        "path": "starter/data/BLLD_VBHN_125-2025.pdf",
        "url": "https://static.luatvietnam.vn/xem-noi-dung-file-van-ban-hop-nhat-125-vbhn-vpqh-nam-2025-do-van-phong-quoc-hoi-ban-hanh-hop-nhat-bo-luat-lao-dong-410920-d5/uploaded/vietlawfile/2025/9/125_vbhn_vpqh_2025_110925084034.pdf.aspx",
        "issuer": "Văn phòng Quốc hội (hợp nhất); văn bản gốc: Quốc hội khóa XIV",
        "version": "VBHN 125/VBHN-VPQH (2025): Bộ luật Lao động 45/2019/QH14 hợp nhất sửa đổi bởi Luật Công nghiệp công nghệ số 71/2025/QH15",
        "license_or_permission": (
            "Văn bản quy phạm pháp luật/văn bản hợp nhất của cơ quan nhà nước không thuộc đối tượng "
            "bảo hộ quyền tác giả (Điều 15 Luật Sở hữu trí tuệ). Bản PDF lấy từ trang lưu trữ công khai "
            "luatvietnam.vn; nội dung là văn bản chính thức, không phải nội dung biên tập của trang."
        ),
        "accessed_at": "2026-11-14",
        "language": "vi",
        "notes": [
            "Ngày ký VBHN không đọc được (trang 86 lỗi text layer); không tự suy đoán.",
            "PDF metadata ModDate 2025-08-27 (iLovePDF/iTextSharp) chỉ là ngày sửa file, không phải ngày hiệu lực.",
            "Đã có VBHN mới hơn (18/VBHN-VPQH năm 2026, bổ sung sửa đổi bởi Luật Dân số 113/2025/QH15); corpus này là snapshot 125/VBHN 2025.",
            "Bản scan có chữ ký (45.signed.pdf, 83 trang ảnh, không có text layer) để ở starter/data/_excluded/, không dùng.",
        ],
    }
]

PAGE_RULE = (
    "Đơn vị = 1 trang PDF vật lý. Trang được tính là trang nội dung khi text layer đọc được "
    "(≥200 chữ cái, tỷ lệ chữ có dấu tiếng Việt ≥0.10, tỷ lệ ký tự rác ≤1%) và chứa nội dung điều luật. "
    "Loại: trang rỗng, trang text layer lỗi/OCR rác. Tài liệu không có bìa, mục lục hay trang tham khảo riêng. "
    "Số trang đầu trang và chú thích cuối trang (footnote về sửa đổi) được tách khỏi nội dung nhưng vẫn lưu trong metadata."
)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def main() -> None:
    t0 = time.perf_counter()
    manifest = {"page_counting_rule": PAGE_RULE, "sources": []}
    all_pages, all_issues = [], []
    for src in SOURCES:
        pdf = ROOT / src["path"]
        if not pdf.exists():
            raise FileNotFoundError(f"Missing corpus file: {pdf}")
        pages, issues, chapter_titles = load_pdf(pdf, src["source_id"], src["path"])
        info = PdfReader(str(pdf)).metadata or {}
        counted = [p for p in pages if p.metadata["counted"]]
        manifest["sources"].append({
            **{k: v for k, v in src.items() if k != "path"},
            "source_path_or_url": {"local": src["path"], "url": src["url"]},
            "sha256": sha256(pdf),
            "pdf_producer": str(info.get("/Producer", "")),
            "physical_pages": len(pages),
            "content_pages_counted": len(counted),
            "counted_page_ids": [p.page for p in counted],
            "excluded_pages": [{"page": p.page, "reason": p.metadata["exclusion_reason"]}
                               for p in pages if not p.metadata["counted"]],
            "chapter_titles": chapter_titles,
            "char_count_normalized_counted": sum(p.metadata["char_count"] for p in counted),
            "pages": [{"page": p.page, "char_count": p.metadata["char_count"],
                       "counted": p.metadata["counted"],
                       "chapters_on_page": p.metadata["chapters_on_page"],
                       "articles_on_page": p.metadata["articles_on_page"]} for p in pages],
        })
        all_pages += pages
        all_issues += [{"source_id": src["source_id"], **i} for i in issues]

    total_counted = sum(s["content_pages_counted"] for s in manifest["sources"])
    manifest["total_content_pages"] = total_counted
    if total_counted < 30:
        raise SystemExit(f"Corpus has only {total_counted} content pages (< 30)")

    (ROOT / "data/processed").mkdir(parents=True, exist_ok=True)
    (ROOT / "results").mkdir(parents=True, exist_ok=True)
    (ROOT / "data/manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    with open(ROOT / "data/processed/pages.jsonl", "w", encoding="utf-8") as f:
        for p in all_pages:
            f.write(json.dumps(asdict(p), ensure_ascii=False) + "\n")
    elapsed = time.perf_counter() - t0
    counted = [p for p in all_pages if p.metadata["counted"]]
    lens = sorted(p.metadata["char_count"] for p in counted)
    log = {
        "elapsed_seconds": round(elapsed, 2),
        "physical_pages": len(all_pages),
        "content_pages_counted": total_counted,
        "chars_counted": sum(lens),
        "chars_per_page": {"min": lens[0], "median": lens[len(lens) // 2], "max": lens[-1]},
        "split_syllables_fixed": {
            "rules": sum(p.metadata["split_syllables_fixed"]["rules"] for p in all_pages),
            "vocab": sum(p.metadata["split_syllables_fixed"]["vocab"] for p in all_pages)},
        "articles_found": sum(len(p.metadata["articles_on_page"]) for p in all_pages),
        "chapters_found": sum(len(p.metadata["chapters_on_page"]) for p in all_pages),
        "normalization_steps": [
            "Unicode NFC, NBSP/tab -> space, gộp khoảng trắng",
            "Bỏ số trang đầu trang (dòng chỉ chứa đúng số trang)",
            "Tách chú thích cuối trang (footnote sửa đổi) sang metadata.footnotes; bỏ số chú thích dính chữ",
            "Nối âm tiết bị tách bởi text layer: luật phụ âm đầu + nguyên âm (c ủa), nguyên âm đôi (ngư ời, vi ệc, tu ổi, quy ền)",
            "Nối âm tiết theo từ vựng của chính tài liệu (lu ật, kho ản, ho ặc): 'ab' xuất hiện >=3 lần và >=2x 'b'",
            "Nối dòng bị ngắt thành đoạn; giữ ranh giới Chương/Mục/Điều/khoản/điểm làm xuống dòng",
        ],
        "known_limitations": [
            "Trang 86 (phần cuối Điều 219, toàn bộ Điều 220 Hiệu lực thi hành, khối ký VBHN) có text layer lỗi, bị loại; không OCR vì máy không có gói tiếng Việt cho tesseract.",
            "Luật nối âm tiết có thể bỏ sót trường hợp hiếm; đã kiểm tra thủ công danh sách cặp được nối (không thấy nối sai).",
            "Trang 1 chứa phần mở đầu VBHN (quốc hiệu, căn cứ) ngoài nội dung điều luật; vẫn tính vì phần lớn trang là Điều 1-3.",
            "Trang 84-85 chủ yếu là Điều 219 sửa đổi luật khác (Luật BHXH, BLTTDS); các 'Điều' được trích dẫn trong đó không được coi là điều của BLLĐ.",
        ],
        "issues": all_issues,
    }
    (ROOT / "results/ingestion_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in log.items() if k != "issues"}, ensure_ascii=False, indent=2))
    print(f"issues: {len(all_issues)} -> results/ingestion_log.json")


if __name__ == "__main__":
    main()
