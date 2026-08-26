"""Computes embeddings for Stage 4 (semantic) matching. Only imported/loaded
when ENABLE_SEMANTIC_MATCH=true — sentence-transformers pulls in torch and a
~90MB model, which is a real RAM risk on a free-tier host (see README
"Turning on semantic matching"). Keeping the import lazy means the app can
run with ENABLE_SEMANTIC_MATCH=false without that dependency ever loading."""

from functools import lru_cache

from app.core.config import get_settings

settings = get_settings()

MODEL_NAME = "all-MiniLM-L6-v2"  # must match kb.ingredient_embeddings.model_name default


@lru_cache
def _get_model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(MODEL_NAME)


def embed(text: str) -> list[float]:
    if not settings.enable_semantic_match:
        raise RuntimeError("ENABLE_SEMANTIC_MATCH is false — embeddings are not available")
    model = _get_model()
    return model.encode(text, normalize_embeddings=True).tolist()


def maybe_embed(text: str) -> list[float] | None:
    """Returns None (skip Stage 4) when semantic matching is disabled,
    instead of raising — this is the call site scans.py actually uses."""
    if not settings.enable_semantic_match:
        return None
    return embed(text)
