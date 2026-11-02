"""Recherche documentaire locale (BM25) pour le RAG.

Aucun modèle d'embedding n'est nécessaire : la base de connaissances est petite
et la recherche lexicale est rapide, déterministe et 100 % hors ligne.
"""

from __future__ import annotations

import logging
import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .config import KNOWLEDGE_DIR

logger = logging.getLogger(__name__)

SOURCE_LABELS = {
    "comptes.md": "Comptes",
    "cartes.md": "Cartes bancaires",
    "credits.md": "Crédits",
    "agences.md": "Agences",
    "reclamations.md": "Réclamations",
    "produits.md": "Produits",
    "faq.md": "FAQ",
}

FRENCH_STOPWORDS = {
    "a", "au", "aux", "avec", "ce", "ces", "cet", "cette", "d", "dans", "de",
    "des", "du", "elle", "en", "et", "eux", "il", "ils", "je", "j", "la", "le",
    "les", "leur", "lui", "ma", "mais", "me", "mes", "moi", "mon", "ne", "nos",
    "notre", "nous", "on", "ou", "où", "par", "pas", "pour", "qu", "que", "qui",
    "sa", "se", "ses", "son", "sur", "ta", "te", "tes", "toi", "ton", "tu", "un",
    "une", "vos", "votre", "vous", "y", "est", "sont", "être", "avoir", "ai",
    "as", "avons", "avez", "ont", "fait", "faire", "plus", "moins", "très",
    "comment", "quel", "quelle", "quels", "quelles", "bonjour", "merci", "svp",
}


def normalize(text: str) -> str:
    """Minuscule + suppression des accents, pour un matching robuste."""
    text = text.lower().replace("\u00a0", " ").replace("’", "'").replace("œ", "oe")
    text = unicodedata.normalize("NFD", text)
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    return text


def tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", normalize(text))
    return [token for token in tokens if len(token) > 1 and token not in FRENCH_STOPWORDS]


@dataclass(frozen=True)
class Chunk:
    source: str
    title: str
    text: str
    tokens: tuple[str, ...]

    @property
    def label(self) -> str:
        return SOURCE_LABELS.get(self.source, self.source)


@dataclass(frozen=True)
class SearchResult:
    chunk: Chunk
    score: float


class KnowledgeBase:
    """Index BM25 construit à partir des fichiers Markdown de la base métier."""

    def __init__(self, directory: Path, k1: float = 1.5, b: float = 0.75):
        self.directory = Path(directory)
        self.k1 = k1
        self.b = b
        self.chunks = self._load_chunks()
        self.term_freqs: list[Counter[str]] = []
        self.doc_lengths: list[int] = []
        self.doc_freqs: Counter[str] = Counter()
        self._build_index()

    def _load_chunks(self) -> list[Chunk]:
        chunks: list[Chunk] = []
        if not self.directory.exists():
            return chunks

        for path in sorted(self.directory.glob("*.md")):
            try:
                raw = path.read_text(encoding="utf-8").strip()
            except (OSError, UnicodeDecodeError):
                logger.warning("Fichier de connaissances illisible : %s", path)
                continue
            if not raw:
                continue
            file_title = path.stem.replace("_", " ").title()
            sections: list[tuple[str, str]] = []
            current_title = file_title
            current_lines: list[str] = []

            for line in raw.splitlines():
                if line.startswith("# ") and not line.startswith("## "):
                    file_title = line[2:].strip() or file_title
                    current_title = file_title
                elif line.startswith("## "):
                    if current_lines:
                        sections.append((current_title, "\n".join(current_lines).strip()))
                    current_title = line[3:].strip()
                    current_lines = []
                else:
                    current_lines.append(line)
            if current_lines:
                sections.append((current_title, "\n".join(current_lines).strip()))

            for title, body in sections:
                if not body:
                    continue
                for part in self._split_long_section(body):
                    tokens = tuple(tokenize(f"{title} {part}"))
                    if tokens:
                        chunks.append(Chunk(path.name, title, part, tokens))
        return chunks

    @staticmethod
    def _split_long_section(text: str, max_chars: int = 900) -> list[str]:
        if len(text) <= max_chars:
            return [text]
        paragraphs = [paragraph.strip() for paragraph in text.split("\n\n") if paragraph.strip()]
        parts: list[str] = []
        current = ""
        for paragraph in paragraphs:
            candidate = f"{current}\n\n{paragraph}".strip()
            if current and len(candidate) > max_chars:
                parts.append(current)
                current = paragraph
            else:
                current = candidate
        if current:
            parts.append(current)
        return parts or [text]

    def _build_index(self) -> None:
        for chunk in self.chunks:
            frequencies = Counter(chunk.tokens)
            self.term_freqs.append(frequencies)
            self.doc_lengths.append(len(chunk.tokens))
            for term in frequencies:
                self.doc_freqs[term] += 1
        total_length = sum(self.doc_lengths)
        self.avgdl = total_length / len(self.doc_lengths) if self.doc_lengths else 1.0

    def search(self, query: str, limit: int = 3) -> list[SearchResult]:
        limit = max(0, int(limit))
        query_tokens = tokenize(query)
        if not query_tokens or not self.chunks or not limit:
            return []

        scores = [0.0] * len(self.chunks)
        total_docs = len(self.chunks)

        for term in set(query_tokens):
            document_frequency = self.doc_freqs.get(term, 0)
            if not document_frequency:
                continue
            idf = math.log(1 + (total_docs - document_frequency + 0.5) / (document_frequency + 0.5))
            for index, frequencies in enumerate(self.term_freqs):
                frequency = frequencies.get(term, 0)
                if not frequency:
                    continue
                length_ratio = self.doc_lengths[index] / self.avgdl
                denominator = frequency + self.k1 * (1 - self.b + self.b * length_ratio)
                scores[index] += idf * (frequency * (self.k1 + 1)) / denominator

        ranked = sorted(
            (SearchResult(self.chunks[index], score) for index, score in enumerate(scores) if score > 0),
            key=lambda result: result.score,
            reverse=True,
        )
        return ranked[:limit]


def format_context(results: list[SearchResult]) -> str:
    blocks = []
    for index, result in enumerate(results, start=1):
        blocks.append(
            f"[{index}] Source : {result.chunk.label} — {result.chunk.title}\n{result.chunk.text}"
        )
    return "\n\n".join(blocks)


_knowledge_base: KnowledgeBase | None = None


def get_knowledge_base() -> KnowledgeBase:
    global _knowledge_base
    if _knowledge_base is None:
        _knowledge_base = KnowledgeBase(KNOWLEDGE_DIR)
    return _knowledge_base
