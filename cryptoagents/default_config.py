"""Configuration management for CryptoTradingAgents"""

import os
from typing import Any

from dotenv import load_dotenv

# Load .env file at module import time
load_dotenv()

_CRYPTOAGENTS_HOME = os.path.join(os.path.expanduser("~"), ".cryptoagents")

# Single source of truth for env-var → config-key overrides
_ENV_OVERRIDES = {
    "CRYPTOAGENTS_LLM_DEEP_THINK_MODEL": "deep_think_llm",
    "CRYPTOAGENTS_LLM_QUICK_THINK_MODEL": "quick_think_llm",
    "CRYPTOAGENTS_LLM_BACKUP_MODEL": "backup_llm",
    "CRYPTOAGENTS_LLM_PROVIDER": "llm_provider",
    "CRYPTOAGENTS_OLLAMA_BASE_URL": "ollama_base_url",
    "CRYPTOAGENTS_OUTPUT_LANGUAGE": "output_language",
    "CRYPTOAGENTS_MAX_DEBATE_ROUNDS": "max_debate_rounds",
    "CRYPTOAGENTS_MAX_RISK_ROUNDS": "max_risk_discuss_rounds",
    "CRYPTOAGENTS_CHECKPOINT_ENABLED": "checkpoint_enabled",
    "CRYPTOAGENTS_TEMPERATURE": "temperature",
    "CRYPTOAGENTS_LLM_MAX_RETRIES": "llm_max_retries",
    "CRYPTOAGENTS_MAX_TOKENS": "max_tokens",
    "CRYPTOAGENTS_TRADEABLE_CRYPTOS": "tradeable_cryptos",
    "CRYPTOAGENTS_INITIAL_PORTFOLIO_VALUE": "initial_portfolio_value",
    "CRYPTOAGENTS_MAX_POSITION_SIZE": "max_position_size",
    "CRYPTOAGENTS_RISK_PER_TRADE": "risk_per_trade",
    "CRYPTOAGENTS_DEBUG": "debug",
}

_BOOL_TRUE = ("true", "1", "yes", "on")
_BOOL_FALSE = ("false", "0", "no", "off")


def _coerce(value: str, reference: Any) -> Any:
    """Coerce env-var string to the type of the existing default value."""
    if isinstance(reference, bool):
        normalized = value.strip().lower()
        if normalized in _BOOL_TRUE:
            return True
        if normalized in _BOOL_FALSE:
            return False
        raise ValueError(
            f"expected a boolean ({'/'.join(_BOOL_TRUE + _BOOL_FALSE)}), got {value!r}"
        )
    if isinstance(reference, int) and not isinstance(reference, bool):
        return int(value)
    if isinstance(reference, float):
        return float(value)
    if isinstance(reference, (list, tuple)):
        # Handle comma-separated values
        return [x.strip() for x in value.split(",")]
    return value


def _apply_env_overrides(config: dict) -> dict:
    """Apply CRYPTOAGENTS_* env vars to the config dict."""
    for env_var, key in _ENV_OVERRIDES.items():
        raw = os.environ.get(env_var)
        if raw is None or raw == "":
            continue
        try:
            config[key] = _coerce(raw, config.get(key))
        except ValueError as exc:
            raise ValueError(f"Invalid value for {env_var}: {exc}") from exc
    return config


DEFAULT_CONFIG = _apply_env_overrides(
    {
        "project_dir": os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
        "results_dir": os.getenv(
            "CRYPTOAGENTS_RESULTS_DIR", os.path.join(_CRYPTOAGENTS_HOME, "logs")
        ),
        "data_cache_dir": os.getenv(
            "CRYPTOAGENTS_CACHE_DIR", os.path.join(_CRYPTOAGENTS_HOME, "cache")
        ),
        "memory_log_path": os.getenv(
            "CRYPTOAGENTS_MEMORY_LOG_PATH",
            os.path.join(_CRYPTOAGENTS_HOME, "memory", "trading_memory.md"),
        ),
        "memory_log_max_entries": None,  # None = unlimited
        # LLM Settings - OpenRouter models (or "ollama" for local models, see CRYPTOAGENTS_LLM_PROVIDER)
        "llm_provider": os.getenv("CRYPTOAGENTS_LLM_PROVIDER", "openrouter"),
        "deep_think_llm": os.getenv("CRYPTOAGENTS_LLM_DEEP_THINK_MODEL", "claude-opus"),
        "quick_think_llm": os.getenv(
            "CRYPTOAGENTS_LLM_QUICK_THINK_MODEL", "gpt-4o"
        ),
        "backup_llm": os.getenv("CRYPTOAGENTS_LLM_BACKUP_MODEL", "deepseek-chat"),
        "backend_url": None,  # OpenRouter default URL
        "ollama_base_url": os.getenv("CRYPTOAGENTS_OLLAMA_BASE_URL", "http://localhost:11434/v1"),
        # Sampling temperature
        "temperature": None,  # None = provider default
        # SDK retry budget
        "llm_max_retries": 3,
        "max_tokens": 8000,
        # Framework tuning
        "output_language": "en",
        "max_debate_rounds": 3,
        "max_risk_discuss_rounds": 2,
        "max_recur_limit": 100,
        "checkpoint_enabled": True,
        # Trading configuration
        "tradeable_cryptos": ["BTC", "ETH", "SOL", "ARB", "OP"],
        "initial_portfolio_value": 100000.0,
        "max_position_size": 0.1,  # 10%
        "risk_per_trade": 0.02,  # 2%
        # API Keys (from environment)
        "openrouter_api_key": os.getenv("OPENROUTER_API_KEY", ""),
        "nansen_api_key": os.getenv("NANSEN_API_KEY", ""),
        "coingecko_api_key": os.getenv("COINGECKO_API_KEY", ""),
        "coinmarketcap_api_key": os.getenv("COINMARKETCAP_API_KEY", ""),
        # Debug mode
        "debug": False,
    }
)
