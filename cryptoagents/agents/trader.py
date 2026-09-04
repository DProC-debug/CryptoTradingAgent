"""Trader Agent - Makes final trading decisions based on research"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class TradeDecision:
    """Final trading decision"""
    signal: str  # "BUY", "SELL", "HOLD"
    position_size: float  # 0.0 to 1.0 (percentage of portfolio)
    entry_price: Optional[float]
    stop_loss: Optional[float]
    take_profit: Optional[float]
    confidence: float  # 0.0 to 1.0
    reasoning: str
    risk_reward_ratio: float
    timestamp: str


class TraderAgent:
    """Trader agent - Makes final trading decisions"""

    def __init__(self, llm_client=None):
        """Initialize trader

        Args:
            llm_client: LLM for complex reasoning
        """
        self.llm_client = llm_client

    def decide(
        self,
        crypto_symbol: str,
        market_data: dict,
        synthesized_score: float,
        debate_result,
        analyst_results: dict,
    ) -> TradeDecision:
        """Make trading decision based on all analysis

        Args:
            crypto_symbol: Cryptocurrency symbol
            market_data: Market data from CoinGecko
            synthesized_score: Average score from all analysts
            debate_result: Result from researcher debate
            analyst_results: Individual analyst results

        Returns:
            TradeDecision with signal and risk parameters
        """
        try:
            current_price = market_data.get("usd", 0)
            
            if not current_price:
                return self._create_neutral_decision(
                    crypto_symbol,
                    "Market data unavailable"
                )

            # Determine signal based on debate and analyst scores
            signal, confidence = self._determine_signal(
                synthesized_score,
                debate_result,
                analyst_results,
            )

            # Calculate position size
            position_size = self._calculate_position_size(
                signal,
                confidence,
                synthesized_score,
            )

            # Calculate risk parameters
            entry_price, stop_loss, take_profit = self._calculate_prices(
                current_price,
                signal,
                analyst_results,
            )

            # Calculate risk/reward ratio
            risk_reward_ratio = self._calculate_risk_reward(
                entry_price,
                stop_loss,
                take_profit,
            )

            # Generate reasoning
            reasoning = self._generate_reasoning(
                signal,
                debate_result,
                synthesized_score,
                position_size,
            )

            return TradeDecision(
                signal=signal,
                position_size=position_size,
                entry_price=entry_price,
                stop_loss=stop_loss,
                take_profit=take_profit,
                confidence=confidence,
                reasoning=reasoning,
                risk_reward_ratio=risk_reward_ratio,
                timestamp=datetime.utcnow().isoformat(),
            )

        except Exception as e:
            logger.error(f"Trader decision error: {e}")
            return self._create_error_decision(str(e))

    def _determine_signal(
        self,
        synthesized_score: float,
        debate_result,
        analyst_results: dict,
    ) -> tuple[str, float]:
        """Determine BUY/SELL/HOLD signal

        Args:
            synthesized_score: Average analyst score
            debate_result: Debate outcome
            analyst_results: Individual analyst results

        Returns:
            Tuple of (signal, confidence)
        """
        # Weight debate result heavily (it incorporates all analysis)
        debate_weight = 0.6
        analyst_weight = 0.4

        # Get debate score
        debate_score = debate_result.consensus_score if debate_result else 0.0

        # Combine scores
        combined_score = (debate_score * debate_weight) + (synthesized_score * analyst_weight)

        logger.info(
            f"[SCORE] debate_score={debate_score:.3f} synthesized_score={synthesized_score:.3f} "
            f"combined_score={combined_score:.3f} (BUY>0.3 / SELL<-0.3)"
        )

        # Determine signal with thresholds
        if combined_score > 0.3:
            signal = "BUY"
            confidence = min(0.95, 0.4 + (combined_score * 0.3))
        elif combined_score < -0.3:
            signal = "SELL"
            confidence = min(0.95, 0.4 + (abs(combined_score) * 0.3))
        else:
            signal = "HOLD"
            # Scaled to the same [~0.5, 0.7] range BUY/SELL can reach, so HOLD never reports
            # higher confidence than an actual trade signal could - most neutral (score near 0)
            # is the most confident HOLD case, closest to the +-0.3 threshold is the least.
            confidence = 0.7 - ((abs(combined_score) / 0.3) * 0.2)

        return signal, confidence

    def _calculate_position_size(
        self,
        signal: str,
        confidence: float,
        synthesized_score: float,
    ) -> float:
        """Calculate position size (0.0 to 1.0)

        Args:
            signal: BUY, SELL, or HOLD
            confidence: Signal confidence
            synthesized_score: Average analyst score

        Returns:
            Position size as percentage
        """
        if signal == "HOLD":
            return 0.3  # Maintain 30% position on HOLD

        # Base position on confidence and score strength
        base_position = 0.5 + (abs(synthesized_score) * 0.25)
        
        # Apply confidence modifier
        position_size = base_position * confidence

        # Cap at 1.0 (100% of allocation for this trade)
        return min(1.0, position_size)

    def _calculate_prices(
        self,
        current_price: float,
        signal: str,
        analyst_results: dict,
    ) -> tuple[Optional[float], Optional[float], Optional[float]]:
        """Calculate entry, stop loss, and take profit prices

        Args:
            current_price: Current market price
            signal: BUY, SELL, or HOLD
            analyst_results: Analyst results for volatility assessment

        Returns:
            Tuple of (entry_price, stop_loss, take_profit)
        """
        if signal == "BUY":
            entry_price = current_price
            # Set stop loss 5% below entry
            stop_loss = current_price * 0.95
            # Set take profit 15% above entry
            take_profit = current_price * 1.15
            return entry_price, stop_loss, take_profit

        elif signal == "SELL":
            entry_price = current_price
            # Set stop loss 5% above entry (for short)
            stop_loss = current_price * 1.05
            # Set take profit 15% below entry
            take_profit = current_price * 0.85
            return entry_price, stop_loss, take_profit

        else:  # HOLD
            return None, None, None

    def _calculate_risk_reward(
        self,
        entry_price: Optional[float],
        stop_loss: Optional[float],
        take_profit: Optional[float],
    ) -> float:
        """Calculate risk/reward ratio

        Args:
            entry_price: Entry price
            stop_loss: Stop loss price
            take_profit: Take profit price

        Returns:
            Risk/reward ratio (reward / risk)
        """
        if not all([entry_price, stop_loss, take_profit]):
            return 0.0

        risk = abs(entry_price - stop_loss)
        reward = abs(take_profit - entry_price)

        if risk == 0:
            return 0.0

        return reward / risk

    def _generate_reasoning(
        self,
        signal: str,
        debate_result,
        synthesized_score: float,
        position_size: float,
    ) -> str:
        """Generate trading reasoning

        Args:
            signal: BUY, SELL, or HOLD
            debate_result: Debate outcome
            synthesized_score: Average analyst score
            position_size: Position size

        Returns:
            Reasoning string
        """
        debate_winner = debate_result.winner if debate_result else "unknown"
        
        if signal == "BUY":
            return (
                f"BUY signal triggered. {debate_winner.capitalize()} researcher consensus "
                f"with {synthesized_score:.0%} analyst bullish bias. "
                f"Recommended position: {position_size:.0%} of allocation. "
                f"Risk/reward favorable for accumulation."
            )
        elif signal == "SELL":
            return (
                f"SELL signal triggered. {debate_winner.capitalize()} researcher consensus "
                f"with {synthesized_score:.0%} bearish bias. "
                f"Recommended position reduction: {position_size:.0%}. "
                f"Protect profits before potential reversal."
            )
        else:
            return (
                f"HOLD signal. Debate is {debate_winner.capitalize()} but weak conviction "
                f"({abs(synthesized_score):.0%} bias). "
                f"Maintain {position_size:.0%} position. "
                f"Await clearer signals before trading."
            )

    def _create_neutral_decision(
        self,
        crypto_symbol: str,
        reason: str,
    ) -> TradeDecision:
        """Create neutral HOLD decision

        Args:
            crypto_symbol: Cryptocurrency symbol
            reason: Reason for neutral decision

        Returns:
            Neutral TradeDecision
        """
        return TradeDecision(
            signal="HOLD",
            position_size=0.5,
            entry_price=None,
            stop_loss=None,
            take_profit=None,
            confidence=0.0,
            reasoning=f"Neutral decision for {crypto_symbol}: {reason}",
            risk_reward_ratio=0.0,
            timestamp=datetime.utcnow().isoformat(),
        )

    def _create_error_decision(self, error: str) -> TradeDecision:
        """Create error decision

        Args:
            error: Error message

        Returns:
            Error TradeDecision
        """
        return TradeDecision(
            signal="HOLD",
            position_size=0.0,
            entry_price=None,
            stop_loss=None,
            take_profit=None,
            confidence=0.0,
            reasoning=f"Trader error: {error}",
            risk_reward_ratio=0.0,
            timestamp=datetime.utcnow().isoformat(),
        )
