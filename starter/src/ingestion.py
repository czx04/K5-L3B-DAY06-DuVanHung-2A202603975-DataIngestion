"""Read and normalize the corpus (Bộ luật Lao động, VBHN 125/VBHN-VPQH).

Each physical PDF page becomes one DocumentPage. Normalization fixes the
text-layer artefacts of this PDF (syllables split by a space, wrapped lines,
running page numbers, footnotes) and keeps legal structure
(Chương / Mục / Điều) as metadata so every chunk can be traced to its page.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from pypdf import PdfReader

from .models import DocumentPage

# ---------------------------------------------------------------- text fixes
_VOWELS = "aăâeêioôơuưyáàảãạắằẳẵặấầẩẫậéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ"
_V = f"[{_VOWELS}{_VOWELS.upper()}]"
# A token made only of an initial consonant (cluster) cannot be a Vietnamese
# syllable, so "c ủa" / "ph ải" / "y t ế" are broken syllables -> join.
_ONSET = r"(?:ngh|ng|nh|ch|gh|kh|ph|th|tr|gi|qu|[bcdđghklmnpqrstvx]|Đ|Ngh|Ng|Nh|Ch|Gh|Kh|Ph|Th|Tr|Gi|Qu)"
_SPLIT_ONSET = re.compile(rf"(?<![\w])({_ONSET}) ({_V})")
# Diphthongs split after their first vowel: "lư ợng", "tu ổi", "vi ệc", "khuy ến".
_SPLIT_DIPH = [
    re.compile(r"(\w*ư) ([ơớờởỡợ]\w*)"),
    re.compile(r"(\w*[^\Wươ]u) ([ôốồổỗộ]\w*)"),
    re.compile(r"(\w*[^\W]i) ([êếềểễệ]\w*)"),
    re.compile(r"(\w*uy) ([êếềểễệ]\w*)"),
]

_PAGE_HEADER = re.compile(r"^\s*(\d{1,3})\s*$")
_CHAPTER = re.compile(r"^Chương ([IVXLC]+)\s*$")
_SECTION = re.compile(r"^Mục (\d+)\.?\s*(.*)$")
_ARTICLE = re.compile(r"^Điều (\d+)\.\s*(.*)$")
_NEW_PARA = re.compile(r"^(Chương [IVXLC]+|Mục \d+|Điều \d+\.|\d+[a-z]?\.\s|[a-zđ]\)\s|“)")
# Footnote block at page bottom: blank line, then "<n> Luật/Khoản/Điều/..."
_FOOTNOTE = re.compile(r"\n\s*\n(\d{1,2} (?:Luật|Khoản|Điều|Điểm|Cụm từ|Từ) .*)\Z", re.S)
_VI_MARKED = set("ăâêôơưđĂÂÊÔƠƯĐ") | {c for c in _VOWELS if c not in "aeiouy"}
_JUNK = set("~{}<>\\|$§¥£")


def fix_split_syllables(line: str) -> tuple[str, int]:
    """Join syllables that the PDF text layer split with a space."""
    n_total = 0
    for _ in range(3):  # several splits can sit next to each other
        line, n = _SPLIT_ONSET.subn(r"\1\2", line)
        n_total += n
        for pat in _SPLIT_DIPH:
            line, n = pat.subn(r"\1\2", line)
            n_total += n
        if n == 0:
            break
    return line, n_total


_WORD = re.compile(r"\w+")


def build_vocab(texts: list[str]) -> dict[str, int]:
    """Token counts of the whole document after rule-based repair."""
    vocab: dict[str, int] = {}
    for t in texts:
        for w in _WORD.findall(t):
            vocab[w] = vocab.get(w, 0) + 1
    return vocab


def join_by_vocab(line: str, vocab: dict[str, int]) -> tuple[str, int]:
    """Join "a b" when b starts with a vowel, is not a word on its own in this
    document (count <= 1) and "ab" is a frequent token (count >= 3).
    Catches splits the rules miss ("lu ật", "ho ạt") without joining real
    word pairs such as "do ảnh" (no token "doảnh"). Condition: "ab" occurs
    >= 3 times and at least twice as often as "b" alone."""
    toks = line.split(" ")
    out, n = [toks[0]], 0
    for tok in toks[1:]:
        prev = out[-1]
        m_prev = re.search(r"(\w+)$", prev)
        m_tok = re.match(r"(\w+)", tok)
        if m_prev and m_tok and re.match(_V, m_tok.group(1)) and not m_prev.group(1).isdigit():
            a, b = m_prev.group(1), m_tok.group(1)
            ab = vocab.get(a + b, 0)
            if ab >= 3 and ab >= 2 * vocab.get(b, 0) and ab >= 2 * vocab.get(a, 0) / 10:
                out[-1] = prev + tok
                n += 1
                continue
        out.append(tok)
    return " ".join(out), n


def text_quality(text: str) -> dict:
    letters = [c for c in text if c.isalpha()]
    n = max(len(letters), 1)
    return {
        "letters": len(letters),
        "vi_marked_ratio": round(sum(c in _VI_MARKED for c in letters) / n, 3),
        "junk_ratio": round(sum(c in _JUNK for c in text) / max(len(text), 1), 4),
    }


def is_garbled(q: dict) -> bool:
    # Normal pages of this law have ~0.30 marked letters; OCR junk has ~0.
    return q["letters"] < 200 or q["vi_marked_ratio"] < 0.10 or q["junk_ratio"] > 0.01


def _is_upper_heading(line: str) -> bool:
    letters = [c for c in line if c.isalpha()]
    return len(letters) >= 3 and all(c.isupper() for c in letters)


def normalize_text(text: str, vocab: dict[str, int] | None = None) -> str:
    """NFC, unify spaces, repair split syllables, rejoin wrapped lines.

    Paragraph boundaries (new Điều/khoản/điểm, headings, sentence ends) are
    kept as single newlines so structure-aware chunking can use them.
    Multi-line upper-case headings are merged into one line; an article
    heading "Điều N. ..." stays on its own line.
    """
    text = unicodedata.normalize("NFC", text).replace("\u00a0", " ").replace("\t", " ")
    paras: list[str] = []
    cur = ""
    for raw in text.split("\n"):
        line = re.sub(r" {2,}", " ", raw).strip()
        if not line:
            if cur:
                paras.append(cur)
                cur = ""
            continue
        line, _ = fix_split_syllables(line)
        if vocab:
            line, _ = join_by_vocab(line, vocab)
        up = _is_upper_heading(line)
        if not cur:
            cur = line
            continue
        cur_up = _is_upper_heading(cur)
        if up and cur_up and not _CHAPTER.match(cur) and not _SECTION.match(cur):
            cur = f"{cur} {line}"          # wrapped upper-case heading
        elif (up or cur_up or _CHAPTER.match(line) or _CHAPTER.match(cur) or _SECTION.match(cur)
              or _NEW_PARA.match(line)
              or cur.endswith((".", ":", ";", ".”", "”.", "”;"))
              or (_ARTICLE.match(cur) and (line[0].isupper() or line[0].isdigit()))):
            paras.append(cur)
            cur = line
        else:
            cur = f"{cur} {line}"
    if cur:
        paras.append(cur)
    return "\n".join(p.strip() for p in paras)


# ---------------------------------------------------------------- loading
def strip_footnote_markers(body: str, footnotes: str) -> tuple[str, list[int]]:
    """Remove superscript footnote numbers glued to words ("Lao động1.")."""
    nums = [int(m.group(1)) for m in re.finditer(r"(?:^|\n)(\d{1,2}) ", footnotes)]
    for n in nums:
        body = re.sub(rf"(?<=[^\W\d]){n}(?=[\s.,;:”]|$)", "", body, count=1)
    return body, nums


def _split_page(raw: str, page_no: int) -> tuple[str, str, bool]:
    """Return (body, footnotes, header_removed)."""
    lines = raw.split("\n")
    header_removed = False
    if lines and (m := _PAGE_HEADER.match(lines[0])) and int(m.group(1)) == page_no:
        lines = lines[1:]
        header_removed = True
    body = "\n".join(lines)
    foot = ""
    if m := _FOOTNOTE.search(body):
        foot = m.group(1)
        body = body[: m.start()]
    return body, foot, header_removed


def load_pdf(path: Path, document_id: str, source: str) -> tuple[list[DocumentPage], list[dict], dict[str, str]]:
    """Extract every physical page, normalize it and tag legal structure.

    Returns (pages, issues, chapter_titles). Pages whose text layer is unusable are still
    returned with metadata["counted"] = False and an exclusion reason.
    """
    reader = PdfReader(str(path))
    pages: list[DocumentPage] = []
    issues: list[dict] = []
    chapter = chapter_title = section = None
    article = 0
    article_title = None
    expect_chapter_title = False
    chapter_titles: dict[str, str] = {}

    raws: list[str] = []
    for idx, pdf_page in enumerate(reader.pages):
        try:
            raws.append(pdf_page.extract_text() or "")
        except Exception as exc:  # keep going, but record it
            raws.append("")
            issues.append({"page": idx + 1, "type": "extract_error", "detail": repr(exc)})
    split = [_split_page(r, i + 1) for i, r in enumerate(raws)]
    # vocabulary from readable pages after rule-based repair (pass 1)
    vocab = build_vocab([
        "\n".join(fix_split_syllables(l)[0] for l in unicodedata.normalize("NFC", b).split("\n"))
        for b, _, _ in split if not is_garbled(text_quality(b))
    ])

    for idx, raw in enumerate(raws):
        page_no = idx + 1
        body, foot, header_removed = split[idx]
        body, foot_nums = strip_footnote_markers(body, foot)
        quality = text_quality(body)
        n_rule = sum(fix_split_syllables(l)[1] for l in body.split("\n"))
        n_vocab = sum(join_by_vocab(fix_split_syllables(l)[0], vocab)[1] for l in body.split("\n"))
        text = normalize_text(body, vocab)
        footnotes = normalize_text(foot, vocab) if foot else ""

        garbled = is_garbled(quality)
        start_ctx = {"chapter": chapter, "chapter_title": chapter_title,
                     "section": section, "article": article or None}
        articles_on_page: list[int] = []
        chapters_on_page: list[str] = []
        if not garbled:
            for line in text.split("\n"):
                if expect_chapter_title and _is_upper_heading(line):
                    chapter_title = line
                    chapter_titles[chapter] = line
                    expect_chapter_title = False
                    continue
                if m := _CHAPTER.match(line):
                    chapter, chapter_title, section = m.group(1), None, None
                    chapters_on_page.append(chapter)
                    expect_chapter_title = True
                elif m := _SECTION.match(line):
                    section = m.group(1)
                elif m := _ARTICLE.match(line):
                    num = int(m.group(1))
                    if num > article:  # ignore quoted articles of other laws
                        article, article_title = num, m.group(2).strip()
                        articles_on_page.append(num)

        meta = {
            "page_label": str(page_no),
            "chapter_at_start": start_ctx["chapter"],
            "article_at_start": start_ctx["article"],
            "chapters_on_page": chapters_on_page,
            "articles_on_page": articles_on_page,
            "chapter_at_end": chapter,
            "chapter_title_at_end": chapter_title,
            "section_at_end": section,
            "char_count_raw": len(raw),
            "char_count": len(text),
            "split_syllables_fixed": {"rules": n_rule, "vocab": n_vocab},
            "footnote_markers_removed": foot_nums,
            "header_removed": header_removed,
            "footnotes": footnotes,
            "quality": quality,
            "counted": not garbled,
            "exclusion_reason": None,
        }
        if garbled:
            meta["exclusion_reason"] = "text layer unreadable (OCR junk, no Vietnamese diacritics)"
            issues.append({"page": page_no, "type": "garbled_text_layer", "detail": quality,
                           "sample": raw[:160]})
        if not raw.strip():
            meta["counted"] = False
            meta["exclusion_reason"] = "empty page"
            issues.append({"page": page_no, "type": "empty_page"})
        if footnotes:
            issues.append({"page": page_no, "type": "footnote_separated", "detail": footnotes[:160]})
        pages.append(DocumentPage(document_id=document_id, source=source,
                                  page=page_no, text=text, metadata=meta))
    return pages, issues, chapter_titles
