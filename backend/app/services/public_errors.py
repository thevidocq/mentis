"""What analysts and tenant admins are told when a service fails.

Errors from the LLM, the embedding service and Qdrant can carry internal addresses and the raw
reply of a provider. Those details are for the super-admin (logs, Service status); everyone else
gets a plain message, unless the error itself is marked `public`.
"""

from app.services.embeddings import EmbeddingError
from app.services.llm import LLMError
from app.services.vector_index import VectorIndexError

AI_UNAVAILABLE = "The AI provider did not answer. Try again in a moment; if it keeps failing, tell your administrator."
SEARCH_UNAVAILABLE = ("The document search service is not available right now. Try again later; "
                      "if it keeps failing, tell your administrator.")


def public_message(e: Exception) -> str:
    if getattr(e, "public", False):
        return str(e)
    if isinstance(e, LLMError):
        return AI_UNAVAILABLE
    if isinstance(e, EmbeddingError | VectorIndexError):
        return SEARCH_UNAVAILABLE
    return "Unexpected error. Tell your administrator."
