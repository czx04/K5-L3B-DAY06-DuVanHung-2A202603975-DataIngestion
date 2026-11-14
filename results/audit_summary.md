# Audit thủ công — tổng hợp

Quy trình chấm: nhãn và lý do do AI (Claude) đề xuất, tác giả đã đọc lại toàn bộ và chấp nhận không sửa ô nào (2026-11-14). Nguy cơ thiên lệch: tác giả cũng là người thiết kế pipeline; nhãn AI có thể bị neo theo kết quả tự động; chỉ một người duyệt, không đo độ đồng thuận.

## Coherence (10 vị trí, thang 0–2; C dùng chung chunk với B)

| Strategy | n | 0/1/2 | Trung bình /2 |
|---|---|---|---|
| A | 10 | 2/6/2 | 1.00 |
| B (= C) | 10 | 0/1/9 | 1.90 |

## Metadata (5 câu test × top-3)

| Strategy | Đủ và đúng | Filter tuân thủ |
|---|---|---|
| A | 9/15 | 1/1 |
| B | 15/15 | 1/1 |
| C | 15/15 | 1/1 |

## Grounding (5 câu test, thang 0–2)

| Strategy | 0/1/2 (số câu) | Trung bình /2 |
|---|---|---|
| A | 2/0/3 | 1.20 |
| B | 1/0/4 | 1.60 |
| C | 1/0/4 | 1.60 |
