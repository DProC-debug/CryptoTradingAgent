"""CryptoTradingAgents: Multi-Agent LLM Crypto Trading Framework"""

__version__ = "0.1.0"
__author__ = "CryptoTradingAgents Contributors"

from cryptoagents.default_config import DEFAULT_CONFIG
from cryptoagents.graph.trading_graph import CryptoTradingGraph

__all__ = [
    "DEFAULT_CONFIG",
    "CryptoTradingGraph",
]
