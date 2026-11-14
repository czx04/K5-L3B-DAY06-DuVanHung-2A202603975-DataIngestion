# Benchmark — Bộ luật Lao động (VBHN 125/2025)

Chốt ngày 2026-11-14, **trước khi chạy bất kỳ cấu hình truy xuất nào**. Không sửa bộ test sau khi xem kết quả; nếu phải sửa sẽ ghi lại ở cuối file này.

- File câu hỏi: `questions.json`. Gồm 20 câu: **15 dev (q01–q15) / 5 test (q16–q20)**.
- Kiểm chứng: `python benchmark/verify_benchmark.py` (chạy từ thư mục gốc repo). Script kiểm tra:
  - mỗi `evidence_quote` có nguyên văn trong text đã chuẩn hóa của `gold_page`, và không xuất hiện ở trang khác;
  - giá trị filter tồn tại trong metadata và khớp chương của trang gold;
  - đủ số câu theo BENCHMARK.md.
  Lần chạy hiện tại: **20/20 OK**.
- Mỗi câu có các trường `id`, `split`, `type`, `question`, `expected_answer`, `gold_source_id`, `gold_page`, `gold_article` (thêm để phân tích lỗi), `evidence_quote`, `filter`.

## Loại câu hỏi

| Loại | Số câu | Ví dụ |
|---|---:|---|
| `truc_tiep` | 6 | q10 giờ làm việc ban đêm |
| `dien_dat_lai` (diễn đạt khác văn bản luật) | 4 | q04 "công ty được trả tôi thấp nhất bao nhiêu khi thử việc" |
| `dieu_kien` | 4 | q02 hợp đồng hết hạn mà vẫn làm việc |
| `ngoai_le` | 2 | q05 hợp đồng dưới 01 tháng không thử việc |
| `metadata_filter` | 4 (3 dev + 1 test) | q20 giờ làm việc của người chưa đủ 15 tuổi, lọc Chương XI |

## Metadata filter

- Trường lọc là `chapter` (số La Mã của Chương), lấy từ heading "Chương …" trong văn bản; không có giá trị nào do đoán.
- Filter là **input giả định được cung cấp trước khi truy xuất**: câu hỏi nêu phạm vi ("theo các quy định riêng đối với lao động nữ…"), như khi người dùng đang xem một chương cụ thể. Filter chỉ chứa chương, không chứa trang hay điều gold.
- Các câu filter được chọn sao cho chương khác có nội dung gây nhiễu:
  - q13 (kết hôn, Chương VII): Chương X cũng nhắc "kết hôn" ở Điều 137.
  - q15 (làm đêm/làm thêm giờ, Chương X): Chương VI và VII quy định chung về làm đêm, làm thêm giờ.
  - q20 (giờ làm việc người chưa đủ 15 tuổi, Chương XI): Điều 105 Chương VII quy định giờ làm việc chung là 8 giờ/ngày.
- Cấu hình C chỉ áp dụng filter cho 4 câu này. Các câu còn lại chạy không filter, giống B.

## Cách chia dev/test và nguy cơ rò rỉ

- Chia **theo chương** để test là các chủ đề chưa dùng khi chỉnh cấu hình:
  - dev: Chương III, VI, VII, X;
  - test: Chương VIII (kỷ luật), XI (lao động chưa thành niên), XII (nghỉ hưu), XIV (tranh chấp).
- Nguy cơ rò rỉ còn lại:
  - Cùng một văn bản và cùng văn phong luật, nên tham số chunk chọn trên dev dễ "hợp" với test.
  - q20 (test) có chủ đề giờ làm việc, gần với q10/q11 (dev, Chương VII).
  - q16 có evidence là một danh sách nhiều dòng, nên nhạy với cách chunk.
- Test chỉ có 5 câu, nên kết quả trên test chỉ mang tính minh họa, không đủ để kết luận tổng quát.

## Tiêu chí chọn chiến lược (chốt trước khi xem test)

Chọn cấu hình **chỉ dựa trên dev**, theo thứ tự ưu tiên:
1. Evidence Hit@3 trên dev, cao hơn là tốt hơn.
2. Nếu bằng nhau: Hit@1 trên dev.
3. Nếu vẫn bằng nhau: điểm coherence trung bình (10 vị trí cố định), rồi tỷ lệ tuân thủ filter trên các câu có filter.
4. Nếu vẫn bằng nhau: tài nguyên, tức ít chunk hơn và ingest nhanh hơn.

Sau khi chọn, cố định cấu hình và chạy test một lần. Kết quả test được báo cáo nguyên như kết quả thu được, không dùng để chỉnh lại cấu hình.

## Nhật ký thay đổi

- 2026-11-14: tạo bộ câu hỏi; chưa có lần chạy truy xuất nào.
- 2026-11-14 10:31: chạy dev → `select` → test (mỗi bước 1 lần). B và C hòa ở mọi tiêu chí đã chốt (Hit@3 14/15, Hit@1 10/15, filter 3/3, cùng index). Tie-break **chưa được chốt trước**: chọn B theo thứ tự trong cấu hình; ghi nhận đây là quyết định sau khi xem dev. Bộ câu hỏi và nhãn không đổi; test chỉ chạy một lần sau khi chọn.
