import math
import re
from collections import Counter
from dataclasses import dataclass

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.rag.ingest import Chunk

RRF_K = 60          # standard constant for Reciprocal Rank Fusion
MIN_BM25 = 1.0      # a result must pass at least one of these two gates
MIN_SIM = 0.20

STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "at", "for", "with", "by", "from",
    "is", "are", "was", "were", "be", "been", "it", "its", "this", "that", "these", "those",
    "as", "not", "no", "if", "then", "than", "so", "we", "you", "they", "he", "she", "do",
    "did", "does", "has", "have", "had", "will", "would", "can", "could", "may", "might",
    "should", "into", "over", "after", "before", "when", "while", "which", "what", "who",
    "all", "any", "each", "every", "also", "only", "there", "their", "them", "but", "about",
    "up", "out",
}
_SUFFIXES = ("ing", "ed", "s")


def _stem(token):
    for suffix in _SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            return token[: -len(suffix)]
    return token


def tokenize(text):
    words = re.findall(r"[a-z0-9]+", text.lower())
    return [_stem(w) for w in words if w not in STOPWORDS and len(w) > 1]


def normalize(text):
    return " ".join(tokenize(text))


class BM25:
    def __init__(self, docs, k1=1.5, b=0.75):
        self.docs = docs
        self.k1 = k1
        self.b = b
        self.n = len(docs)
        self.avgdl = (sum(len(d) for d in docs) / self.n) if self.n else 1.0
        if self.avgdl == 0:
            self.avgdl = 1.0
        df = Counter()
        for d in docs:
            df.update(set(d))
        self.idf = {t: math.log(1 + (self.n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
        self.tfs = [Counter(d) for d in docs]

    def score(self, query_tokens):
        scores = []
        for i, tf in enumerate(self.tfs):
            dl = len(self.docs[i])
            total = 0.0
            for t in set(query_tokens):
                f = tf.get(t, 0)
                if not f:
                    continue
                denom = f + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
                total += self.idf[t] * f * (self.k1 + 1) / denom
            scores.append(total)
        return scores


@dataclass
class Hit:
    chunk: Chunk
    fused: float
    bm25: float
    similarity: float

    @property
    def strong(self):
        """Strong match = both searches agree it is relevant."""
        return self.bm25 >= MIN_BM25 and self.similarity >= MIN_SIM


def _ranks(scores):
    order = sorted((i for i, s in enumerate(scores) if s > 0), key=lambda i: scores[i], reverse=True)
    return {idx: rank for rank, idx in enumerate(order, start=1)}


def search(query, chunks, top_k=5, per_doc=2):
    """Hybrid search over the chunks given. Statistics are computed only on these chunks,
    so call it with role-filtered chunks and restricted documents can never influence scoring."""
    if not chunks:
        return []
    docs_norm = [normalize(c.search_text) for c in chunks]
    query_norm = normalize(query)
    if not query_norm or not any(docs_norm):
        return []

    bm25_scores = BM25([d.split() for d in docs_norm]).score(query_norm.split())

    vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True)
    matrix = vectorizer.fit_transform(docs_norm)
    sims = cosine_similarity(vectorizer.transform([query_norm]), matrix)[0].tolist()

    fused = {}
    for ranks in (_ranks(bm25_scores), _ranks(sims)):
        for idx, rank in ranks.items():
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (RRF_K + rank)

    hits = []
    for idx, score in fused.items():
        if bm25_scores[idx] >= MIN_BM25 or sims[idx] >= MIN_SIM:
            hits.append(Hit(chunks[idx], score, bm25_scores[idx], sims[idx]))
    hits.sort(key=lambda h: h.fused, reverse=True)

    picked = []
    per_doc_count = Counter()
    for hit in hits:
        if per_doc_count[hit.chunk.doc_id] >= per_doc:
            continue
        per_doc_count[hit.chunk.doc_id] += 1
        picked.append(hit)
        if len(picked) >= top_k:
            break
    return picked