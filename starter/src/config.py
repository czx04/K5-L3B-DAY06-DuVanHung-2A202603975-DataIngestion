"""Single source of truth for the three strategies (same corpus, model, store)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGES_FILE = ROOT / "data/processed/pages.jsonl"
QUESTIONS_FILE = ROOT / "benchmark/questions.json"
RESULTS = ROOT / "results"
TOP_K = 3
# B/C max_size = 800 chars (not 1000) because the embedding model truncates at
# 256 PhoBERT tokens; chosen from the model limit BEFORE any retrieval run.

# index = which stored chunk set is searched; C reuses B's chunks so that
# B vs C differs ONLY in the metadata filter.
STRATEGIES = {
    "A": {"index": "A", "chunking": "fixed_size", "params": {"size": 500, "overlap": 50},
          "use_filter": False,
          "description": "Cửa sổ 500 ký tự, overlap 50, cắt trong từng trang; metadata nguồn/trang/chương; không lọc"},
    "B": {"index": "B", "chunking": "by_article", "params": {"max_size": 800},
          "use_filter": False,
          "description": "Theo Điều/khoản, tối đa 800 ký tự, không trộn 2 Điều, đoạn tiếp nối có tiền tố tiêu đề Điều; không lọc"},
    "C": {"index": "B", "chunking": "by_article", "params": {"max_size": 800},
          "use_filter": True,
          "description": "Giống B; lọc chapter khi câu hỏi có filter (câu không có filter chạy như B)"},
}
