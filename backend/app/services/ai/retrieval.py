"""Protocol retrieval (the R in RAG).

Deliberately lexical, not embedding-based:

* it must run inside Uzbekistan with no external embedding call;
* it must be deterministic and explainable — a clinician can be shown exactly
  which passage produced an answer;
* the corpus is small and curated, so recall is not the bottleneck.

The retriever is also the *safety boundary*: if nothing scores above the
threshold, the assistant has no grounds to answer and the question is escalated
to the patient's doctor (spec 8). That decision is made from retrieval scores,
never delegated to the language model.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai import Protocol, ProtocolChunk

_APOSTROPHES = {"‘", "’", "ʻ", "ʼ", "`", "´", "ʹ"}

# Very common words carry no retrieval signal in any of the three languages.
_STOPWORDS = {
    # uz
    "va",
    "bilan",
    "uchun",
    "bu",
    "men",
    "meni",
    "mening",
    "siz",
    "sizning",
    "qanday",
    "qancha",
    "nima",
    "bormi",
    "kerak",
    "mumkin",
    "ham",
    "yoki",
    "lekin",
    "agar",
    "juda",
    "biroz",
    "hozir",
    "bugun",
    "yana",
    # ru
    "и",
    "в",
    "на",
    "с",
    "у",
    "к",
    "по",
    "за",
    "для",
    "что",
    "как",
    "это",
    "мне",
    "мой",
    "моя",
    "вы",
    "ваш",
    "быть",
    "если",
    "или",
    "но",
    "очень",
    "можно",
    "нужно",
    "сегодня",
    "ещё",
    "еще",
    # en
    "the",
    "a",
    "an",
    "and",
    "or",
    "but",
    "if",
    "is",
    "are",
    "was",
    "were",
    "to",
    "of",
    "in",
    "on",
    "for",
    "with",
    "my",
    "me",
    "i",
    "you",
    "your",
    "how",
    "what",
    "can",
    "should",
    "do",
    "does",
    "it",
    "this",
    "that",
}


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "").lower()
    for ch in _APOSTROPHES:
        text = text.replace(ch, "'")
    return text


def tokenize(text: str) -> list[str]:
    normalized = _normalize(text)
    tokens = re.findall(r"[\w']+", normalized, flags=re.UNICODE)
    return [t for t in tokens if len(t) > 2 and t not in _STOPWORDS]


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    chunk_id: str
    protocol_slug: str
    protocol_title: str
    heading: str | None
    content: str
    score: float


class LexicalIndex:
    """In-memory BM25-style index over the protocol chunks of one locale.

    The corpus is a few hundred passages, so it is loaded per request and scored
    directly; there is no background index to keep in sync.
    """

    K1 = 1.4
    B = 0.72

    def __init__(self, documents: list[tuple[ProtocolChunk, Protocol]]) -> None:
        self._docs = documents
        self._tokens: list[list[str]] = []
        self._doc_freq: Counter[str] = Counter()
        for chunk, _protocol in documents:
            # Tags are indexed alongside the body so short keyword questions
            # ("gipoglikemiya?") still hit the right passage.
            tags = " ".join(str(t) for t in (chunk.tags or []))
            tokens = tokenize(f"{chunk.heading or ''} {tags} {chunk.content}")
            self._tokens.append(tokens)
            self._doc_freq.update(set(tokens))
        self._avg_len = (
            sum(len(t) for t in self._tokens) / len(self._tokens) if self._tokens else 0.0
        )

    def search(self, query: str, *, top_k: int = 5) -> list[RetrievedChunk]:
        query_tokens = tokenize(query)
        if not query_tokens or not self._docs:
            return []

        n_docs = len(self._docs)
        results: list[RetrievedChunk] = []
        # Self-score of the query bounds the raw BM25 sum, which turns the score
        # into a 0..1 relevance ratio that a fixed threshold can be applied to.
        max_possible = sum(self._idf(t) * (self.K1 + 1) for t in set(query_tokens)) or 1.0

        for index, (chunk, protocol) in enumerate(self._docs):
            tokens = self._tokens[index]
            if not tokens:
                continue
            counts = Counter(tokens)
            length = len(tokens)
            score = 0.0
            for token in set(query_tokens):
                tf = counts.get(token, 0)
                if not tf:
                    continue
                idf = self._idf(token)
                denominator = tf + self.K1 * (
                    1 - self.B + self.B * (length / (self._avg_len or 1.0))
                )
                score += idf * (tf * (self.K1 + 1)) / denominator
            if score <= 0:
                continue
            results.append(
                RetrievedChunk(
                    chunk_id=str(chunk.id),
                    protocol_slug=protocol.slug,
                    protocol_title=(protocol.title or {}).get("uz", protocol.slug),
                    heading=chunk.heading,
                    content=chunk.content,
                    score=round(min(score / max_possible, 1.0), 4),
                )
            )
            _ = n_docs  # documented above; kept for clarity of the BM25 shape

        results.sort(key=lambda r: -r.score)
        return results[:top_k]

    def _idf(self, token: str) -> float:
        n_docs = len(self._docs)
        df = self._doc_freq.get(token, 0)
        # BM25 idf with the +1 smoothing that keeps common terms non-negative.
        return math.log(1 + (n_docs - df + 0.5) / (df + 0.5))


async def retrieve(
    db: AsyncSession,
    query: str,
    *,
    locale: str,
    allowed_slugs: list[str] | None = None,
    top_k: int = 5,
    min_score: float = 0.12,
) -> list[RetrievedChunk]:
    """Search the active protocol corpus.

    ``allowed_slugs`` scopes retrieval to the protocols the patient's diagnosis
    template authorises, so an asthma patient is never answered from a diabetes
    protocol. ``general_safety`` is always in scope.
    """
    stmt = (
        sa.select(ProtocolChunk, Protocol)
        .join(Protocol, Protocol.id == ProtocolChunk.protocol_id)
        .where(Protocol.is_active.is_(True), ProtocolChunk.locale == locale)
    )
    if allowed_slugs:
        slugs = list({*allowed_slugs, "general_safety"})
        stmt = stmt.where(Protocol.slug.in_(slugs))

    rows = list((await db.execute(stmt)).all())
    if not rows:
        return []

    index = LexicalIndex([(row[0], row[1]) for row in rows])
    hits = index.search(query, top_k=top_k)
    return [hit for hit in hits if hit.score >= min_score]
