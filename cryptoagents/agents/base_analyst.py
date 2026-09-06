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

    def _calculate_score(
        self,
        positive_factors: int,
        negative_factors: int,
        neutral_factors: int = 0,
    ) -> tuple[float, float]:
        """Calculate bullish/bearish score from factors

        Args:
            positive_factors: Count of bullish indicators
            negative_factors: Count of bearish indicators
            neutral_factors: Count of neutral indicators

        Returns:
            Tuple of (score, confidence) where score is -1.0 to 1.0
        """
        total_factors = positive_factors + negative_factors + neutral_factors

        if total_factors == 0:
            return 0.0, 0.0

        # Calculate raw score
        raw_score = (positive_factors - negative_factors) / total_factors

        # Confidence based on number of factors and agreement
        confidence = (len([x for x in [positive_factors, negative_factors] if x > 0]) / 2)

        return raw_score, confidence
