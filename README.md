# Bài làm Day 06 — Data Ingestion: Bộ luật Lao động (VBHN 125/2025)

Học viên: Dư Văn Hùng · 2A202603975 · L3B — xem [STUDENT.md](STUDENT.md) và [báo cáo cá nhân](report/individual/2A202603975_DuVanHung.md).

## Kết quả chính

| Strategy | Dev Hit@1 | Dev Hit@3 | Test Hit@1 | Test Hit@3 | Coherence /2 | Grounding /2 (test) |
|---|---|---|---|---|---|---|
| A — fixed 500/50 | 6/15 | 10/15 | 2/5 | 3/5 | 1.00 | 1.20 |
| **B — theo Điều ≤800 (chọn)** | 10/15 | 14/15 | 3/5 | 4/5 | 1.90 | 1.60 |
| C — B + filter chương | 10/15 | 14/15 | 3/5 | 4/5 | 1.90 | 1.60 |

## Cấu trúc

| Đường dẫn | Nội dung |
|---|---|
| `starter/data/BLLD_VBHN_125-2025.pdf` | Corpus (văn bản QPPL, không thuộc đối tượng bảo hộ quyền tác giả) |
| `data/manifest.json` | Nguồn, giấy phép, phiên bản, sha256, trang được tính/loại, số ký tự |
| `data/processed/pages.jsonl` | Text đã chuẩn hóa từng trang + metadata Chương/Mục/Điều |
| `benchmark/` | 20 câu hỏi (15 dev/5 test), script kiểm chứng evidence, tiêu chí chọn chiến lược |
| `starter/src/` | Pipeline: `ingestion.py`, `ingest.py`, `chunking.py`, `embeddings.py`, `store.py`, `evaluation.py`, `audit.py`, `run.py`, `config.py` |
| `artifacts/experiment_log.csv` | Cấu hình, giả thuyết, kết quả A/B/C |
| `results/` | `ingestion_log.json`, `index_run.json`, `chunks_*.jsonl`, `traces/`, `metrics_{dev,test}.{json,md}`, `selection.json`, `audit/`, `audit_summary.md` |

## Setup và chạy (macOS/Linux, Python 3.11+, Docker)

```bash
cd starter
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt            # psycopg, pypdf, sentence-transformers, pyvi
cp .env.example .env                       # DATABASE_URL, EMBEDDING_MODEL=bkai-foundation-models/vietnamese-bi-encoder
docker compose -p day6_student_starter up -d --wait   # PostgreSQL 16 + pgvector 0.8.7
python scripts/check_setup.py

python -m src.ingest                       # 1. PDF -> pages.jsonl, manifest, ingestion log
python ../benchmark/verify_benchmark.py    # 2. kiểm chứng evidence của 20 câu
python -m src.run index                    # 3. chunk A/B, embed, lưu pgvector, kiểm tra nạp lại
python -m src.run eval --split dev         # 4. trace + Hit@1/Hit@3 trên dev
python -m src.run select                   # 5. chọn chiến lược chỉ dựa trên dev
python -m src.run eval --split test        # 6. test (bị chặn nếu chưa select)
python -m src.run audit                    # 7. sinh bảng chấm tay
python -m src.run audit-summary            # 8. tổng hợp nhãn
```

Model embedding chạy local; nếu chưa có trong cache Hugging Face thì bỏ `HF_HUB_OFFLINE=1` trong `.env` để tải (~517 MB) lần đầu. Chi phí: $0.

---

# Đề bài

# Day 06 · Data Ingestion Engineering

**Lab cá nhân** · **4 giờ** · **Dữ liệu tự chọn**

Biến tài liệu thành kho tri thức có thể truy xuất cho AI agent, rồi đo xem cách chuẩn bị dữ liệu nào hiệu quả nhất.

| 📄 Dữ liệu | 🧩 Chiến lược | 🎯 Benchmark |
|---|---|---|
| Tối thiểu **30 trang nội dung** | Tối thiểu **3 cấu hình** | Tối thiểu **20 câu hỏi** |

## Bắt đầu nhanh

Dùng [starter PostgreSQL + pgvector](starter/README.md) để dựng database và hoàn thiện các hàm TODO, hoặc tự chọn vector store tương đương. Starter chỉ là khung: **bạn tự hiện thực pipeline và benchmark**.

## 1. Xây pipeline

![Đọc tài liệu, chuẩn hóa, chia chunk, tạo vector, lưu và kiểm tra](assets/ingestion-pipeline.svg)

Chọn tài liệu được phép sử dụng; giữ **ID tài liệu, nguồn, trang/vị trí** và metadata phù hợp. Dùng embedding model thật qua API hoặc chạy local; lưu và truy xuất bằng pgvector, Qdrant, Chroma hoặc một store tương đương.

## 2. So sánh và đánh giá

![Ba chiến lược được đánh giá trên cùng corpus và benchmark dev/test](assets/benchmark-workflow.svg)

Dùng cùng dữ liệu, model và câu hỏi cho cả ba cấu hình. Tách **15 câu dev / 5 câu test** trước khi chạy; chọn cấu hình trên dev, rồi đánh giá test sau khi cố định. Mỗi câu hỏi cần có đoạn bằng chứng và trang nguồn; thiết kế bộ câu hỏi và đánh giá theo [BENCHMARK.md](BENCHMARK.md).

Đánh giá theo năm khía cạnh: **độ chính xác truy xuất**, **tính mạch lạc của chunk**, **tính hữu dụng của metadata**, **chất lượng grounding** và **tác động của chiến lược dữ liệu**. Giải thích lựa chọn bằng kết quả, ví dụ lỗi và các đánh đổi.

## 3. Chuẩn bị bài nộp

1. Chạy pipeline và lưu cấu hình, kết quả top-3, trace cùng nhãn đánh giá thủ công.
2. Điền [thông tin học viên](STUDENT.md), [nhật ký thí nghiệm](artifacts/experiment_log.csv) và bản sao [mẫu báo cáo cá nhân](report/individual/MSSV_HoTen.md).
3. Kiểm tra mã nguồn, cách chạy, manifest dữ liệu và checklist trong [SUBMISSION.md](SUBMISSION.md).

## Tài liệu hướng dẫn

| Bạn cần tìm | Tài liệu |
|---|---|
| Setup baseline PostgreSQL + pgvector | [starter/README.md](starter/README.md) |
| Các bước làm và cách tính chỉ số | [GUIDE.md](GUIDE.md) |
| Tiến độ trong 4 giờ | [CHECKPOINTS.md](CHECKPOINTS.md) |
| Năm tiêu chí benchmark và bộ câu hỏi | [BENCHMARK.md](BENCHMARK.md) |
| Tiêu chí chấm điểm | [RUBRIC.md](RUBRIC.md) |
| Quy tắc sử dụng dữ liệu, AI và API | [RULES.md](RULES.md) |
| Cách nộp bài | [SUBMISSION.md](SUBMISSION.md) |

[data/format-example.json](data/format-example.json) chỉ minh họa định dạng, không phải corpus đủ điều kiện. Phần xử lý và benchmark do bạn tự hiện thực; không bắt buộc xây chatbot.
