import logging

from fastembed import TextEmbedding

from app.config import settings


class Embedder:
    def __init__(self):
        self.model_name = settings.EMBED_MODEL
        try:
            self.model = TextEmbedding(self.model_name, cache_dir=settings.FASTEMBED_CACHE_PATH)
        except Exception as e:
            logging.error(f"Failed to load fastembed model: {e}")
            self.model = None

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        if not self.model: return []
        return list(self.model.embed(texts))

    def embed_query(self, text: str) -> list[float]:
        if not self.model: return []
        return list(self.model.query_embed(text))[0]

embedder = Embedder()
