"""Text -> vector. Runs locally (no API, no cost): BAAI/bge-small-en-v1.5, 384 dimensions,
about 130 MB, downloaded once to the Hugging Face cache.

Vectors are normalised, so cosine similarity is a dot product. bge models expect queries
(not passages) to carry an instruction prefix; `embed_query` adds it.
"""

from typing import Any, Protocol

EMBEDDING_DIM = 384
DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class Embedder(Protocol):
    model_name: str
    dim: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class LocalEmbedder:
    dim = EMBEDDING_DIM

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        self.model_name = model_name
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is None:  # loading takes seconds; only when first needed
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
        return self._model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors = self._load().encode(texts, normalize_embeddings=True, batch_size=32)
        return [list(map(float, v)) for v in vectors]

    def embed_query(self, text: str) -> list[float]:
        vector = self._load().encode([_QUERY_PREFIX + text], normalize_embeddings=True)[0]
        return list(map(float, vector))
