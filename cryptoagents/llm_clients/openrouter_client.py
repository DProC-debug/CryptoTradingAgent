"""OpenRouter LLM client for accessing multiple models via unified API"""

import logging
from typing import Any, Optional

from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)


class OpenRouterClient:
    """Client for interacting with LLMs via OpenRouter API, or a local OpenAI-compatible
    server (e.g. Ollama) when provider='ollama'"""

    def __init__(
        self,
        api_key: str,
        model: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: int = 30,
        base_url: Optional[str] = None,
        **kwargs: Any,
    ):
        """Initialize OpenRouter/local client

        Args:
            api_key: OpenRouter API key (ignored for local providers)
            model: Model name (e.g., 'claude-opus', 'gpt-4o', 'qwen3:14b')
            temperature: Sampling temperature (0-2)
            max_tokens: Maximum tokens in response
            timeout: Request timeout in seconds
            base_url: Override endpoint (used for local providers like Ollama)
            **kwargs: Additional arguments passed to ChatOpenAI
        """
        is_local = base_url is not None
        if not is_local and not api_key:
            raise ValueError("OPENROUTER_API_KEY not set in environment")

        self.model = model
        self.api_key = api_key

        # OpenRouter/Ollama both expose an OpenAI-compatible API format
        client_kwargs = {
            "model": model,
            "api_key": api_key or "ollama",  # ChatOpenAI requires a non-empty string
            "base_url": base_url or "https://openrouter.ai/api/v1",
            "timeout": timeout,
        }
        if not is_local:
            client_kwargs["default_headers"] = {
                "HTTP-Referer": "https://github.com/cryptoagents",
            }

        if temperature is not None:
            client_kwargs["temperature"] = temperature

        if max_tokens is not None:
            client_kwargs["max_tokens"] = max_tokens

        # Merge additional kwargs
        client_kwargs.update(kwargs)

        self.client = ChatOpenAI(**client_kwargs)

    def get_llm(self) -> ChatOpenAI:
        """Get the LLM client instance"""
        return self.client

    def invoke(self, messages: list, **kwargs: Any) -> str:
        """Invoke the LLM with messages

        Args:
            messages: List of message dicts with 'role' and 'content'
            **kwargs: Additional arguments

        Returns:
            LLM response text
        """
        response = self.client.invoke(messages, **kwargs)
        return response.content


# Available OpenRouter models for different use cases
OPENROUTER_MODELS = {
    "deep_think": [
        "openai/gpt-4-turbo",  # Best reasoning
        "openai/gpt-4",  # High quality
        "openai/gpt-4o",  # Balanced and fast
    ],
    "quick_think": [
        "openai/gpt-4o",  # Fast and capable
        "openai/gpt-4-turbo",  # Fast reasoning
        "openai/gpt-3.5-turbo",  # Reliable and fast
    ],
    "backup": [
        "openai/gpt-3.5-turbo",  # Fallback
        "google/gemini-2.0-flash",  # Alternative fast model
        "meta-llama/llama-3-70b",  # Open source alternative
    ],
}


def create_llm_client(
    provider: str,
    model: str,
    api_key: Optional[str] = None,
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    base_url: Optional[str] = None,
    **kwargs: Any,
) -> OpenRouterClient:
    """Factory function to create LLM clients

    Args:
        provider: Provider name ('openrouter' or 'ollama' for local models)
        model: Model name
        api_key: API key (unused for 'ollama')
        temperature: Sampling temperature
        max_tokens: Max tokens
        base_url: Local server URL, required for provider='ollama'
        **kwargs: Additional arguments

    Returns:
        OpenRouterClient instance
    """
    provider = provider.lower()
    if provider not in ("openrouter", "ollama"):
        raise ValueError(f"Unsupported provider: {provider}")

    return OpenRouterClient(
        api_key=api_key,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        base_url=base_url if provider == "ollama" else None,
        **kwargs,
    )
