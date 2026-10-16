"""LLM provider abstraction.

Every model is reachable only through :class:`~app.platform.llm.base.LLMProvider`: Gemini
by default, or an OpenAI-compatible endpoint (a model served by vLLM) when
``LLM_HOST`` is set. No agent or service code depends on which one answers.
"""

from app.platform.llm.base import LLMProvider, LLMUnavailable, NullProvider
from app.platform.llm.gemini import GeminiProvider, get_provider
from app.platform.llm.openai_compat import OpenAICompatProvider

__all__ = [
    "GeminiProvider",
    "LLMProvider",
    "LLMUnavailable",
    "NullProvider",
    "OpenAICompatProvider",
    "get_provider",
]
