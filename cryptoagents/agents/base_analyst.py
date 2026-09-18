"""Base Analyst class for all specialized analysts"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class AnalysisResult:
    """Result from an analyst"""
    analyst_type: str
    score: float  # -1.0 (bearish) to 1.0 (bullish)
    confidence: float  # 0.0 to 1.0
    reasoning: str
    key_metrics: dict
    timestamp: str


class BaseAnalyst(ABC):
    """Base class for all analysts in the trading system"""

    def __init__(self, name: str, llm_client=None):
        """Initialize analyst

        Args:
            name: Analyst name (blockchain, sentiment, technical, etc)
            llm_client: LLM client for reasoning
        """
        self.name = name
        self.llm_client = llm_client

    @abstractmethod
    async def analyze(
        self,
        crypto_symbol: str,
        market_data: dict,
        additional_context: Optional[dict] = None,
    ) -> AnalysisResult:
        """Run analysis on cryptocurrency

        Args:
            crypto_symbol: Symbol like BTC, ETH
            market_data: Market data from CoinGecko
            additional_context: Any additional data for analysis

        Returns:
            AnalysisResult with score and reasoning
        """
        pass
