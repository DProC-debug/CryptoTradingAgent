"""Researcher agents - Bullish and Bearish debate agents"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class DebatePoint:
    """A single point in the debate"""
    position: str  # "bullish" or "bearish"
    argument: str
    supporting_evidence: list[str]
    confidence: float  # 0.0 to 1.0


@dataclass
class DebateResult:
    """Result of a debate between researchers"""
    winner: str  # "bullish" or "bearish"
    consensus_score: float  # -1.0 to 1.0
    bullish_arguments: list[DebatePoint]
    bearish_arguments: list[DebatePoint]
    debate_reasoning: str
    timestamp: str


class BaseResearcher(ABC):
    """Base class for researcher agents"""

    # Symmetric bar for both sides - a score must clear this magnitude to count as evidence
    SCORE_THRESHOLD = 0.2

    def __init__(self, position: str, llm_client=None):
        """Initialize researcher

        Args:
            position: 'bullish' or 'bearish'
            llm_client: LLM for reasoning
        """
        self.position = position
        self.llm_client = llm_client

    @abstractmethod
    def build_arguments(
        self,
        crypto_symbol: str,
        analyses: dict,
        market_data: dict,
    ) -> list[DebatePoint]:
        """Build arguments for the debate

        Args:
            crypto_symbol: Cryptocurrency symbol
            analyses: Dict of analyst results
            market_data: Market data

        Returns:
            List of debate points supporting this researcher's position
        """
        pass

    def _extract_supporting_scores(self, analyses: dict) -> list[float]:
        """Extract scores from analyst results

        Args:
            analyses: Dict of analyst results

        Returns:
            List of scores
        """
        scores = []
        for analyst_name, result in analyses.items():
            if result and hasattr(result, 'score'):
                scores.append(result.score)
        return scores

    def _confidence_from_magnitude(self, score_magnitude: float) -> float:
        """Scale an argument's confidence by how strong the underlying signal actually is,
        instead of a fixed constant - a 0.9 score should count for more than a 0.21 score.

        Args:
            score_magnitude: abs() of the analyst score that triggered this argument

        Returns:
            Confidence in [0.5, 0.95]
        """
        return min(0.95, 0.5 + (score_magnitude * 0.45))


class BullishResearcher(BaseResearcher):
    """Bullish researcher - argues for upside"""

    def __init__(self, llm_client=None):
        super().__init__("bullish", llm_client)

    def build_arguments(
        self,
        crypto_symbol: str,
        analyses: dict,
        market_data: dict,
    ) -> list[DebatePoint]:
        """Build bullish arguments from analyst data

        Args:
            crypto_symbol: Cryptocurrency symbol
            analyses: Dict of analyst results
            market_data: Market data

        Returns:
            List of bullish debate points
        """
        arguments = []
        scores = self._extract_supporting_scores(analyses)
        t = self.SCORE_THRESHOLD

        # Check sentiment strength
        if analyses.get("sentiment") and hasattr(analyses["sentiment"], 'score'):
            score = analyses["sentiment"].score
            if score > t:
                arguments.append(DebatePoint(
                    position="bullish",
                    argument="Strong positive social sentiment indicates community optimism",
                    supporting_evidence=[
                        f"Sentiment score: {score:.2f}",
                        "FOMO/Euphoria emotions detected in community"
                    ],
                    confidence=self._confidence_from_magnitude(score),
                ))

        # Check technical strength
        if analyses.get("technical") and hasattr(analyses["technical"], 'score'):
            score = analyses["technical"].score
            if score > t:
                arguments.append(DebatePoint(
                    position="bullish",
                    argument="Positive technical signals indicate price momentum building",
                    supporting_evidence=[
                        f"Technical score: {score:.2f}",
                        "Uptrend pattern forming",
                        "Positive MACD histogram"
                    ],
                    confidence=self._confidence_from_magnitude(score),
                ))

        # Check macro conditions
        if analyses.get("macro") and hasattr(analyses["macro"], 'score'):
            score = analyses["macro"].score
            if score > t:
                arguments.append(DebatePoint(
                    position="bullish",
                    argument="Macro market conditions are favoring growth assets",
                    supporting_evidence=[
                        f"Macro score: {score:.2f}",
                        "Bullish market phase detected",
                        "Favorable altseason conditions"
                    ],
                    confidence=self._confidence_from_magnitude(score),
                ))

        # Check fundamentals
        if analyses.get("fundamental") and hasattr(analyses["fundamental"], 'score'):
            score = analyses["fundamental"].score
            if score > t:
                arguments.append(DebatePoint(
                    position="bullish",
                    argument="Strong project fundamentals support long-term value",
                    supporting_evidence=[
                        f"Fundamental score: {score:.2f}",
                        "Low inflation rate",
                        "Active development"
                    ],
                    confidence=self._confidence_from_magnitude(score),
                ))

        # Overall momentum argument
        avg_score = sum(scores) / len(scores) if scores else 0
        if avg_score > t:
            arguments.append(DebatePoint(
                position="bullish",
                argument="Consensus bullish bias across multiple analysis frameworks",
                supporting_evidence=[
                    f"Average analyst score: {avg_score:.2f}",
                    f"Positive signals: {sum(1 for s in scores if s > 0)}/{len(scores)} analysts"
                ],
                confidence=self._confidence_from_magnitude(avg_score),
            ))

        return arguments if arguments else [self._default_bullish_argument()]

    def _default_bullish_argument(self) -> DebatePoint:
        """Default argument when insufficient data"""
        return DebatePoint(
            position="bullish",
            argument="Limited bearish signals suggest continued upside potential",
            supporting_evidence=["Conservative analysis approach"],
            confidence=0.4,
        )


class BearishResearcher(BaseResearcher):
    """Bearish researcher - argues for downside"""

    def __init__(self, llm_client=None):
        super().__init__("bearish", llm_client)

    def build_arguments(
        self,
        crypto_symbol: str,
        analyses: dict,
        market_data: dict,
    ) -> list[DebatePoint]:
        """Build bearish arguments from analyst data

        Args:
            crypto_symbol: Cryptocurrency symbol
            analyses: Dict of analyst results
            market_data: Market data

        Returns:
            List of bearish debate points
        """
        arguments = []
        scores = self._extract_supporting_scores(analyses)
        t = self.SCORE_THRESHOLD

        # Check blockchain data
        if analyses.get("blockchain") and hasattr(analyses["blockchain"], 'score'):
            score = analyses["blockchain"].score
            if score < -t:
                arguments.append(DebatePoint(
                    position="bearish",
                    argument="Whale activity and on-chain metrics show accumulation slowing",
                    supporting_evidence=[
                        f"Blockchain score: {score:.2f}",
                        "Reduced whale accumulation",
                        "Minimal on-chain activity"
                    ],
                    confidence=self._confidence_from_magnitude(abs(score)),
                ))

        # Check technical weakness
        if analyses.get("technical") and hasattr(analyses["technical"], 'score'):
            score = analyses["technical"].score
            if score < -t:
                arguments.append(DebatePoint(
                    position="bearish",
                    argument="Technical indicators suggest weak momentum and potential reversal",
                    supporting_evidence=[
                        f"Technical score: {score:.2f}",
                        "RSI entering overbought territory",
                        "Resistance levels nearby"
                    ],
                    confidence=self._confidence_from_magnitude(abs(score)),
                ))

        # Check macro risks
        if analyses.get("macro") and hasattr(analyses["macro"], 'score'):
            score = analyses["macro"].score
            if score < -t:
                arguments.append(DebatePoint(
                    position="bearish",
                    argument="Macro conditions show potential headwinds for crypto",
                    supporting_evidence=[
                        f"Macro score: {score:.2f}",
                        "BTC dominance elevated",
                        "Distribution phase possible"
                    ],
                    confidence=self._confidence_from_magnitude(abs(score)),
                ))

        # Valuation concern
        if market_data.get("usd_market_cap", 0) > 1e12:
            arguments.append(DebatePoint(
                position="bearish",
                argument="Large market cap limits upside potential; profit-taking risk high",
                supporting_evidence=[
                    f"Market cap: ${market_data.get('usd_market_cap', 0):,.0f}",
                    "Extended rally may face resistance"
                ],
                confidence=0.55,
            ))

        # Risk warning argument
        avg_score = sum(scores) / len(scores) if scores else 0
        if avg_score < -t and len(arguments) > 0:
            arguments.append(DebatePoint(
                position="bearish",
                argument="Consensus bearish bias across multiple analysis frameworks",
                supporting_evidence=[
                    f"Average analyst score: {avg_score:.2f}",
                    f"Negative signals: {sum(1 for s in scores if s < 0)}/{len(scores)} analysts"
                ],
                confidence=self._confidence_from_magnitude(abs(avg_score)),
            ))

        return arguments if arguments else [self._default_bearish_argument()]

    def _default_bearish_argument(self) -> DebatePoint:
        """Default argument when insufficient data"""
        return DebatePoint(
            position="bearish",
            argument="Lack of clear bullish signals warrants cautious approach",
            supporting_evidence=["Uncertainty premium justified"],
            confidence=0.4,
        )


class ResearcherDebate:
    """Orchestrates debate between bullish and bearish researchers"""

    def __init__(self, llm_client=None):
        """Initialize debate

        Args:
            llm_client: LLM for reasoning
        """
        self.bullish_researcher = BullishResearcher(llm_client)
        self.bearish_researcher = BearishResearcher(llm_client)
        self.llm_client = llm_client

    def debate(
        self,
        crypto_symbol: str,
        analyses: dict,
        market_data: dict,
    ) -> DebateResult:
        """Run debate between researchers

        Args:
            crypto_symbol: Cryptocurrency symbol
            analyses: Dict of analyst results
            market_data: Market data

        Returns:
            DebateResult with arguments and consensus
        """
        # Build arguments from both sides
        bullish_args = self.bullish_researcher.build_arguments(
            crypto_symbol, analyses, market_data
        )
        bearish_args = self.bearish_researcher.build_arguments(
            crypto_symbol, analyses, market_data
        )

        # Calculate consensus score
        consensus = self._calculate_consensus(bullish_args, bearish_args)

        # Determine winner
        if consensus > 0.2:
            winner = "bullish"
        elif consensus < -0.2:
            winner = "bearish"
        else:
            winner = "neutral"

        reasoning = self._generate_reasoning(
            winner,
            bullish_args,
            bearish_args,
            consensus,
        )

        return DebateResult(
            winner=winner,
            consensus_score=consensus,
            bullish_arguments=bullish_args,
            bearish_arguments=bearish_args,
            debate_reasoning=reasoning,
            timestamp=datetime.utcnow().isoformat(),
        )

    def _calculate_consensus(
        self,
        bullish_args: list[DebatePoint],
        bearish_args: list[DebatePoint],
    ) -> float:
        """Calculate consensus score from debate points

        Args:
            bullish_args: Bullish debate points
            bearish_args: Bearish debate points

        Returns:
            Consensus score from -1.0 to 1.0
        """
        bullish_confidence = sum(arg.confidence for arg in bullish_args) / len(bullish_args) if bullish_args else 0
        bearish_confidence = sum(arg.confidence for arg in bearish_args) / len(bearish_args) if bearish_args else 0

        # Confidence-weighted consensus
        if bullish_confidence + bearish_confidence > 0:
            consensus = (bullish_confidence - bearish_confidence) / (bullish_confidence + bearish_confidence)
        else:
            consensus = 0.0

        return max(-1.0, min(1.0, consensus))

    def _generate_reasoning(
        self,
        winner: str,
        bullish_args: list[DebatePoint],
        bearish_args: list[DebatePoint],
        consensus: float,
    ) -> str:
        """Generate reasoning for debate outcome

        Args:
            winner: 'bullish', 'bearish', or 'neutral'
            bullish_args: Bullish arguments
            bearish_args: Bearish arguments
            consensus: Consensus score

        Returns:
            Reasoning string
        """
        consensus_pct = abs(consensus) * 100

        bullish_count = len(bullish_args)
        bearish_count = len(bearish_args)

        if winner == "bullish":
            return (
                f"Bullish researcher prevails ({consensus_pct:.0f}% confidence). "
                f"Arguments: {bullish_count} bullish vs {bearish_count} bearish. "
                f"Key strength: Multiple positive analyst signals align."
            )
        elif winner == "bearish":
            return (
                f"Bearish researcher prevails ({consensus_pct:.0f}% confidence). "
                f"Arguments: {bearish_count} bearish vs {bullish_count} bullish. "
                f"Key concern: Risk/reward asymmetry favors downside protection."
            )
        else:
            return (
                f"Researchers reach stalemate ({consensus_pct:.0f}% consensus). "
                f"Arguments: {bullish_count} bullish vs {bearish_count} bearish. "
                f"Recommendation: HOLD pending clearer signals."
            )
