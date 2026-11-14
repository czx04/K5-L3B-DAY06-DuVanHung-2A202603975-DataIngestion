"""Real embedding providers. No mock/random fallback: errors are raised.

Default: bkai-foundation-models/vietnamese-bi-encoder (PhoBERT-base-v2,
768 dims, trained incl. Zalo 2021 legal text retrieval). Input MUST be
word-segmented (pyvi), max 256 tokens. Also supported: intfloat/multilingual-e5-*
(prefixes "query: " / "passage: "). Vectors are L2-normalized.
Optional: OpenAI text-embedding-3-small via EMBEDDING_PROVIDER=openai.
"""
from __future__ import annotations

import os
import platform
from typing import Protocol


class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, question: str) -> list[float]: ...
    def info(self) -> dict: ...


class LocalSTEmbedder:
    """Sentence Transformers model run locally (bkai vietnamese-bi-encoder or e5)."""

    def __init__(self, model_name: str = "bkai-foundation-models/vietnamese-bi-encoder", batch_size: int = 32) -> None:
        try:
            import sentence_transformers
            import torch
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # do not fall back to fake vectors
            raise RuntimeError("Install sentence-transformers: pip install -r requirements.txt") from exc
        device = "mps" if torch.backends.mps.is_available() else ("cuda" if torch.cuda.is_available() else "cpu")
        self.model_name = model_name
        self.batch_size = batch_size
        self.model = SentenceTransformer(model_name, device=device)
        self.is_e5 = "e5" in model_name.lower()
        self.segment = "vietnamese-bi-encoder" in model_name.lower()
        if self.segment:
            try:
                from pyvi import ViTokenizer
            except ImportError as exc:
                raise RuntimeError("vietnamese-bi-encoder needs word segmentation: pip install pyvi") from exc
            self._seg = ViTokenizer.tokenize
        if self.is_e5:
            self.model.max_seq_length = 512
        self.max_seq_length = int(self.model.max_seq_length)
        dim_fn = getattr(self.model, "get_embedding_dimension", None) or self.model.get_sentence_embedding_dimension
        self.dimensions = int(dim_fn())
        self._versions = {"sentence_transformers": sentence_transformers.__version__,
                          "torch": torch.__version__, "device": device}

    def _encode(self, texts: list[str]) -> list[list[float]]:
        vecs = self.model.encode(texts, batch_size=self.batch_size, normalize_embeddings=True,
                                 convert_to_numpy=True, show_progress_bar=len(texts) > 64)
        return vecs.tolist()

    def _prep(self, text: str, kind: str) -> str:
        if self.segment:
            text = self._seg(text)
        if self.is_e5:
            text = f"{kind}: {text}"
        return text

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._encode([self._prep(t, "passage") for t in texts])

    def embed_query(self, question: str) -> list[float]:
        return self._encode([self._prep(question, "query")])[0]

    def token_lengths(self, texts: list[str]) -> list[int]:
        tok = self.model.tokenizer
        return [len(tok(self._prep(t, "passage"), truncation=False)["input_ids"]) for t in texts]

    def info(self) -> dict:
        revision = None
        try:  # commit hash of the cached model snapshot, if available offline
            from huggingface_hub import scan_cache_dir
            for repo in scan_cache_dir().repos:
                if repo.repo_id == self.model_name:
                    revision = sorted(r.commit_hash for r in repo.revisions)[-1]
        except Exception:
            pass
        return {"provider": "local (Sentence Transformers / Hugging Face cache)", "model": self.model_name,
                "revision": revision, "dimensions": self.dimensions, "normalize": True,
                "preprocessing": ("pyvi word segmentation" if self.segment else "none")
                                 + ("; prefixes query:/passage:" if self.is_e5 else "; same for query and document"),
                "max_seq_length": self.max_seq_length,
                "python": platform.python_version(), **self._versions, "cost_usd": 0.0}


class OpenAIEmbedder:
    PRICE_PER_1M_TOKENS = None  # fill from current pricing page if you use it

    def __init__(self, model_name: str = "text-embedding-3-small") -> None:
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY missing")
        from openai import OpenAI
        self.client = OpenAI()
        self.model_name = model_name
        self.dimensions = len(self.embed_query("ping"))
        self.tokens = 0

    def _embed(self, texts: list[str]) -> list[list[float]]:
        out = []
        for i in range(0, len(texts), 128):
            r = self.client.embeddings.create(model=self.model_name, input=texts[i:i + 128])
            self.tokens += r.usage.total_tokens
            out += [d.embedding for d in r.data]
        return out

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts)

    def embed_query(self, question: str) -> list[float]:
        return self._embed([question])[0]

    def info(self) -> dict:
        return {"provider": "openai", "model": self.model_name, "dimensions": self.dimensions,
                "tokens_used": self.tokens}


def get_embedder() -> Embedder:
    provider = os.getenv("EMBEDDING_PROVIDER", "local").lower()
    model = os.getenv("EMBEDDING_MODEL") or None
    if provider == "local":
        return LocalSTEmbedder(model or "bkai-foundation-models/vietnamese-bi-encoder")
    if provider == "openai":
        return OpenAIEmbedder(model or "text-embedding-3-small")
    raise RuntimeError(f"Unknown EMBEDDING_PROVIDER={provider}")
