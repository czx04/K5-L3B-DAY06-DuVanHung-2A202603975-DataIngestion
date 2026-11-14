"""Chunking strategies.

A  fixed_size   : sliding character window per page (size/overlap), no structure.
B  by_article   : structure-aware; one unit = the part of one Điều on one page,
                  paragraphs (khoản/điểm) grouped greedily up to max_size, each
                  chunk prefixed with its article heading so it reads on its own.
C  = B chunks + metadata filter at query time (no separate index).

Every chunk lives on exactly one PDF page, so `page` is always exact.
Chunk IDs are deterministic (document, strategy, page, position) and a
content hash is stored to detect changed text on re-ingest.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .models import Chunk, DocumentPage

_CHAPTER = re.compile(r"^Chương ([IVXLC]+)\s*$")
_SECTION = re.compile(r"^Mục (\d+)\b")
_ARTICLE = re.compile(r"^Điều (\d+)\.\s*(.*)$")


@dataclass
class Para:
    page: int
    text: str
    chapter: str | None
    chapter_title: str | None
    section: str | None
    article: int | None
    article_heading: str | None
    is_heading: bool


def annotate(pages: list[DocumentPage]) -> list[Para]:
    """Walk the document in order and attach Chương/Mục/Điều to each paragraph."""
    chapter = chapter_title = section = heading = None
    article = 0
    want_title = False
    out: list[Para] = []
    for p in pages:
        for line in p.text.split("\n"):
            is_heading = False
            if want_title:
                chapter_title, want_title, is_heading = line, False, True
            elif m := _CHAPTER.match(line):
                chapter, section, want_title, is_heading = m.group(1), None, True, True
            elif m := _SECTION.match(line):
                section, is_heading = m.group(1), True
            elif (m := _ARTICLE.match(line)) and int(m.group(1)) > article:
                article, heading = int(m.group(1)), line
            elif section and out and out[-1].is_heading and out[-1].text.startswith("Mục") and line.isupper():
                is_heading = True  # section title line
            out.append(Para(p.page, line, chapter, chapter_title, section,
                            article or None, heading if article else None, is_heading))
    return out


def _hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _chunk(doc: DocumentPage, strategy: str, idx: int, text: str, meta: dict) -> Chunk:
    return Chunk(
        chunk_id=f"{doc.document_id}:{strategy}:p{doc.page:03d}:{idx:03d}",
        document_id=doc.document_id, source=doc.source, page=doc.page, text=text,
        metadata={**meta, "strategy": strategy, "content_hash": _hash(text), "char_count": len(text)},
    )


def fixed_size(page: DocumentPage, paras: list[Para], size: int = 500, overlap: int = 50,
               strategy: str = "A") -> list[Chunk]:
    """Character windows over the page text. Metadata = context at window start."""
    if overlap >= size:
        raise ValueError("overlap must be smaller than size")
    page_paras = [p for p in paras if p.page == page.page]
    text, starts = "", []
    for p in page_paras:
        starts.append(len(text))
        text += p.text + "\n"
    text = text.rstrip("\n")
    chunks, pos, idx = [], 0, 0
    while pos < len(text):
        piece = text[pos: pos + size].strip()
        if piece:
            # paragraph containing the window start
            k = max(i for i, s in enumerate(starts) if s <= pos) if starts else 0
            ctx = page_paras[k] if page_paras else None
            chunks.append(_chunk(page, strategy, idx, piece, {
                "chapter": ctx.chapter if ctx else None,
                "chapter_title": ctx.chapter_title if ctx else None,
                "section": ctx.section if ctx else None,
                "article": ctx.article if ctx else None,
                "char_start": pos,
            }))
            idx += 1
        if pos + size >= len(text):
            break
        pos += size - overlap
    return chunks


def _split_long(text: str, max_size: int) -> list[str]:
    """Split an oversized paragraph at sentence / clause ends, then hard-cut."""
    parts = re.split(r"(?<=[.;:])\s+", text)
    out, cur = [], ""
    for part in parts:
        if len(part) > max_size:
            if cur:
                out.append(cur)
                cur = ""
            out += [part[i: i + max_size] for i in range(0, len(part), max_size)]
        elif len(cur) + len(part) + 1 <= max_size:
            cur = f"{cur} {part}".strip()
        else:
            out.append(cur)
            cur = part
    if cur:
        out.append(cur)
    return out


def by_article(page: DocumentPage, paras: list[Para], max_size: int = 1000,
               strategy: str = "B") -> list[Chunk]:
    """Group paragraphs of the same Điều on this page, up to max_size chars.

    A chunk never mixes two articles or two chapters. Continuation chunks
    (later part of an article, or an article continued from the previous page)
    get the article heading prefixed so they are self-explanatory.
    """
    page_paras = [p for p in paras if p.page == page.page]
    groups: list[list[Para]] = []
    pending: list[Para] = []  # chapter/section heading lines wait for the next article
    for p in page_paras:
        if p.is_heading:
            pending.append(p)
            continue
        starts_article = bool(_ARTICLE.match(p.text)) and p.article_heading == p.text
        same = groups and (groups[-1][-1].chapter, groups[-1][-1].article) == (p.chapter, p.article)
        if pending or starts_article or not same:
            groups.append(pending + [p])
            pending = []
        else:
            groups[-1].append(p)
    if pending:  # headings at the very end of a page
        groups.append(pending)

    chunks, idx = [], 0
    for g in groups:
        body = [p for p in g]
        ref = next((p for p in reversed(g) if not p.is_heading), g[-1])
        only_headings = all(p.is_heading for p in g)  # e.g. "Chương XVI" at page bottom
        heading = None if only_headings else ref.article_heading
        pieces: list[str] = []
        cur = ""
        for p in body:
            for t in (_split_long(p.text, max_size) if len(p.text) > max_size else [p.text]):
                if cur and len(cur) + len(t) + 1 > max_size:
                    pieces.append(cur)
                    cur = t
                else:
                    cur = f"{cur}\n{t}" if cur else t
        if cur:
            pieces.append(cur)
        for piece in pieces:
            text = piece
            if heading and heading not in piece:
                text = f"{heading} (tiếp)\n{piece}"
            chunks.append(_chunk(page, strategy, idx, text, {
                "chapter": ref.chapter, "chapter_title": ref.chapter_title,
                "section": ref.section, "article": None if only_headings else ref.article,
                "heading_prefixed": text != piece,
            }))
            idx += 1
    return chunks


def build_chunks(pages: list[DocumentPage], strategy: str, params: dict) -> list[Chunk]:
    paras = annotate(pages)
    out: list[Chunk] = []
    for page in pages:
        if strategy == "A":
            out += fixed_size(page, paras, params["size"], params["overlap"], "A")
        elif strategy == "B":
            out += by_article(page, paras, params["max_size"], "B")
        else:
            raise ValueError(f"unknown chunking strategy {strategy}")
    return out
