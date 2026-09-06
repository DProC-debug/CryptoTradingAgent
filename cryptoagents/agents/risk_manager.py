"""Risk Manager - Portfolio risk assessment and risk-adjusted recommendations"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List
import math

logger = logging.getLogger(__name__)


@dataclass
class RiskMetrics:
    """Individual trade risk assessment"""
    trade_signal: str  # BUY, SELL, HOLD
    position_size: float  # 0.0 to 1.0
    entry_price: Optional[float]
    stop_loss: Optional[float]
    take_profit: Optional[float]
    
    # Risk metrics
    risk_amount: Optional[float]  # Dollar amount at risk
    reward_amount: Optional[float]  # Potential profit
    risk_reward_ratio: float  # reward / risk
    loss_percentage: Optional[float]  # % loss at stop
    gain_percentage: Optional[float]  # % gain at target
    
    # Risk-adjusted position
    adjusted_position_size: float  # Position size after risk adjustment
    max_portfolio_loss: float  # Max % loss of total portfolio
    
    reasoning: str
    timestamp: str


@dataclass
class PortfolioRiskReport:
    """Portfolio-level risk assessment"""
    total_portfolio_value: float
    num_positions: int
    
    # Risk metrics
    portfolio_volatility: float  # Standard deviation
    sharpe_ratio: float  # Return per unit of risk (assume 0% risk-free rate)
    sortino_ratio: float  # Return per unit of downside risk
    max_drawdown: float  # Worst peak-to-trough decline
    
    # Aggregate risk
    total_at_risk: float  # Total $ at risk across all positions
    portfolio_beta: float  # Market sensitivity
    correlation_matrix: dict  # Asset correlations
    
    # Risk warnings
    warnings: List[str]
    
    # Recommendations
    recommendations: List[str]
    
    overall_risk_level: str  # "LOW", "MEDIUM", "HIGH", "CRITICAL"
    risk_score: float  # 0 (safest) to 100 (riskiest)
    
    timestamp: str


class RiskManager:
    """Manages portfolio risk and provides risk-adjusted recommendations"""

    def __init__(self, portfolio_value: float = 100000.0, llm_client=None):
        """Initialize risk manager

        Args:
            portfolio_value: Total portfolio value in USD
            llm_client: LLM for reasoning
        """
        self.portfolio_value = portfolio_value
        self.llm_client = llm_client
        self.risk_free_rate = 0.0  # Assume 0% for crypto
        self.max_portfolio_risk_pct = 0.02  # Max 2% of portfolio at risk per trade

    def assess_trade_risk(
        self,
        trade_decision,
        market_data: dict,
    ) -> RiskMetrics:
        """Assess risk for a single trade

        Args:
            trade_decision: TradeDecision from trader
            market_data: Market data from CoinGecko

        Returns:
            RiskMetrics with risk assessment
        """
        try:
            current_price = market_data.get("usd", 0)
            
            if not current_price:
                return self._create_neutral_risk_metrics(trade_decision)

            # Calculate base risk amounts
            risk_amount = None
            reward_amount = None
            loss_pct = None
            gain_pct = None

            if trade_decision.signal in ["BUY", "SELL"] and trade_decision.entry_price:
                risk_amount = abs(trade_decision.entry_price - trade_decision.stop_loss)
                reward_amount = abs(trade_decision.take_profit - trade_decision.entry_price)
                
                loss_pct = (risk_amount / trade_decision.entry_price) * 100
                gain_pct = (reward_amount / trade_decision.entry_price) * 100

            # Calculate max portfolio loss from this trade
            if risk_amount:
                max_portfolio_loss = (risk_amount * trade_decision.position_size) / self.portfolio_value
            else:
                max_portfolio_loss = 0.0

            # Adjust position size based on risk limits
            adjusted_position = self._adjust_position_for_risk(
                trade_decision.position_size,
                max_portfolio_loss,
                trade_decision.confidence,
            )

            reasoning = self._generate_trade_reasoning(
                trade_decision.signal,
                risk_amount,
                reward_amount,
                max_portfolio_loss,
                adjusted_position,
            )

            return RiskMetrics(
                trade_signal=trade_decision.signal,
                position_size=trade_decision.position_size,
                entry_price=trade_decision.entry_price,
                stop_loss=trade_decision.stop_loss,
                take_profit=trade_decision.take_profit,
                risk_amount=risk_amount,
                reward_amount=reward_amount,
                risk_reward_ratio=trade_decision.risk_reward_ratio,
                loss_percentage=loss_pct,
                gain_percentage=gain_pct,
                adjusted_position_size=adjusted_position,
                max_portfolio_loss=max_portfolio_loss,
                reasoning=reasoning,
                timestamp=datetime.utcnow().isoformat(),
            )

        except Exception as e:
            logger.error(f"Risk assessment error: {e}")
            return self._create_error_risk_metrics(str(e))

    def _adjust_position_for_risk(
        self,
        original_position: float,
        max_portfolio_loss: float,
        confidence: float,
    ) -> float:
        """Adjust position size based on risk constraints

        Args:
            original_position: Original position size (0-1)
            max_portfolio_loss: Max % loss of portfolio
            confidence: Trade confidence (0-1)

        Returns:
            Adjusted position size
        """
        # Don't exceed portfolio risk limit
        if max_portfolio_loss > self.max_portfolio_risk_pct:
            # Scale down to fit risk limit
            adjustment_factor = self.max_portfolio_risk_pct / max_portfolio_loss
            adjusted = original_position * adjustment_factor
        else:
            adjusted = original_position

        # Further adjust based on confidence
        # Low confidence = smaller position
        confidence_factor = 0.5 + (confidence * 0.5)  # 0.5 to 1.0
        adjusted = adjusted * confidence_factor

        # Cap at 1.0
        return min(1.0, adjusted)

    def assess_portfolio_risk(
        self,
        positions: List[dict],
        prices: List[float],
        price_history: Optional[dict] = None,
    ) -> PortfolioRiskReport:
        """Assess overall portfolio risk

        Args:
            positions: List of position dicts with 'symbol', 'size', 'entry_price'
            prices: List of current prices corresponding to positions
            price_history: Historical price data for volatility calculation

        Returns:
            PortfolioRiskReport with comprehensive risk metrics
        """
        try:
            num_positions = len(positions)
            
            if num_positions == 0:
                return self._create_empty_portfolio_report()

            # Calculate position values
            position_values = [
                pos.get("size", 0) * price 
                for pos, price in zip(positions, prices)
            ]
            total_value = sum(position_values)

            # Calculate portfolio weights
            weights = [pv / total_value for pv in position_values] if total_value > 0 else []

            # Calculate volatility
            volatility = self._calculate_volatility(price_history, prices)

            # Calculate Sharpe ratio
            sharpe = self._calculate_sharpe_ratio(volatility)

            # Calculate Sortino ratio
            sortino = self._calculate_sortino_ratio(volatility, price_history)

            # Calculate max drawdown
            max_dd = self._calculate_max_drawdown(price_history) if price_history else 0.0

            # Calculate portfolio beta
            beta = self._calculate_portfolio_beta(positions)

            # Calculate correlations
            correlations = self._calculate_correlations(positions)

            # Calculate total at risk
            total_at_risk = self._calculate_total_at_risk(positions, prices)

            # Generate warnings and recommendations
            warnings, recommendations, risk_level = self._generate_risk_analysis(
                volatility,
                sharpe,
                max_dd,
                num_positions,
                total_at_risk,
                weights,
            )

            # Calculate overall risk score
            risk_score = self._calculate_risk_score(
                volatility,
                max_dd,
                num_positions,
                total_at_risk,
            )

            return PortfolioRiskReport(
                total_portfolio_value=total_value,
                num_positions=num_positions,
                portfolio_volatility=volatility,
                sharpe_ratio=sharpe,
                sortino_ratio=sortino,
                max_drawdown=max_dd,
                total_at_risk=total_at_risk,
                portfolio_beta=beta,
                correlation_matrix=correlations,
                warnings=warnings,
                recommendations=recommendations,
                overall_risk_level=risk_level,
                risk_score=risk_score,
                timestamp=datetime.utcnow().isoformat(),
            )

        except Exception as e:
            logger.error(f"Portfolio risk assessment error: {e}")
            return self._create_error_portfolio_report(str(e))

    def _calculate_volatility(
        self,
        price_history: Optional[dict],
        current_prices: List[float],
    ) -> float:
        """Calculate portfolio volatility (standard deviation of returns)

        Args:
            price_history: Historical price data
            current_prices: Current prices

        Returns:
            Volatility as decimal (0.2 = 20%)
        """
        if not price_history:
            return 0.05  # Default 5% volatility estimate

        # Simplified: use last 30 returns
        returns = []
        for prices in price_history.values():
            if len(prices) > 1:
                for i in range(1, min(31, len(prices))):
                    ret = (prices[i] - prices[i-1]) / prices[i-1]
                    returns.append(ret)

        if not returns:
            return 0.05

        # Calculate standard deviation
        mean_return = sum(returns) / len(returns)
        variance = sum((r - mean_return) ** 2 for r in returns) / len(returns)
        volatility = math.sqrt(variance)

        return volatility

    def _calculate_sharpe_ratio(self, volatility: float) -> float:
        """Calculate Sharpe ratio

        Args:
            volatility: Portfolio volatility

        Returns:
            Sharpe ratio
        """
        if volatility == 0:
            return 0.0
        
        # Assume mean return of 20% annually for crypto
        mean_return = 0.20
        
        sharpe = (mean_return - self.risk_free_rate) / volatility
        return sharpe

    def _calculate_sortino_ratio(
        self,
        volatility: float,
        price_history: Optional[dict],
    ) -> float:
        """Calculate Sortino ratio (downside deviation only)

        Args:
            volatility: Portfolio volatility
            price_history: Historical price data

        Returns:
            Sortino ratio
        """
        if not price_history or volatility == 0:
            return self._calculate_sharpe_ratio(volatility) * 0.8

        # Simplified: use downside volatility
        downside_volatility = volatility * 0.7  # Assume downside is 70% of total vol
        
        mean_return = 0.20
        sortino = (mean_return - self.risk_free_rate) / downside_volatility if downside_volatility > 0 else 0

        return sortino

    def _calculate_max_drawdown(self, price_history: Optional[dict]) -> float:
        """Calculate maximum drawdown

        Args:
            price_history: Historical price data

        Returns:
            Max drawdown as decimal (-0.3 = -30%)
        """
        if not price_history:
            return -0.15  # Default estimate

        max_dd = 0.0
        for prices in price_history.values():
            if len(prices) > 1:
                peak = prices[0]
                for price in prices[1:]:
                    if price > peak:
                        peak = price
                    drawdown = (price - peak) / peak
                    max_dd = min(max_dd, drawdown)

        return max_dd

    def _calculate_portfolio_beta(self, positions: List[dict]) -> float:
        """Calculate portfolio beta (market sensitivity)

        Args:
            positions: List of positions

        Returns:
            Portfolio beta (1.0 = market)
        """
        # Simplified: crypto has ~0.8 beta to market
        # Vary based on asset mix
        if not positions:
            return 1.0

        # Average crypto asset beta
        avg_beta = sum(pos.get("beta", 1.2) for pos in positions) / len(positions)

        return avg_beta

    def _calculate_correlations(self, positions: List[dict]) -> dict:
        """Calculate asset correlations

        Args:
            positions: List of positions

        Returns:
            Correlation matrix
        """
        # Simplified correlations for common crypto assets
        correlation_map = {
            ("BTC", "ETH"): 0.75,
            ("BTC", "SOL"): 0.65,
            ("ETH", "SOL"): 0.70,
            ("BTC", "DOGE"): 0.60,
            ("ETH", "DOGE"): 0.55,
        }

        correlations = {}
        for i, pos1 in enumerate(positions):
            for j, pos2 in enumerate(positions):
                if i < j:
                    key = (pos1.get("symbol"), pos2.get("symbol"))
                    corr = correlation_map.get(key, 0.7)
                    correlations[f"{key[0]}-{key[1]}"] = corr

        return correlations

    def _calculate_total_at_risk(
        self,
        positions: List[dict],
        prices: List[float],
    ) -> float:
        """Calculate total dollar amount at risk

        Args:
            positions: List of positions
            prices: Current prices

        Returns:
            Total value at risk ($)
        """
        total_at_risk = 0.0
        
        for pos, price in zip(positions, prices):
            stop_loss = pos.get("stop_loss", price * 0.95)
            loss_per_unit = price - stop_loss
            loss_amount = loss_per_unit * pos.get("size", 0)
            total_at_risk += max(0, loss_amount)

        return total_at_risk

    def _generate_risk_analysis(
        self,
        volatility: float,
        sharpe: float,
        max_dd: float,
        num_positions: int,
        total_at_risk: float,
        weights: List[float],
    ) -> tuple[List[str], List[str], str]:
        """Generate risk warnings, recommendations, and overall level

        Args:
            volatility: Portfolio volatility
            sharpe: Sharpe ratio
            max_dd: Max drawdown
            num_positions: Number of positions
            total_at_risk: Total $ at risk
            weights: Position weights

        Returns:
            Tuple of (warnings, recommendations, risk_level)
        """
        warnings = []
        recommendations = []

        # Check volatility
        if volatility > 0.3:
            warnings.append(f"High volatility ({volatility:.1%})")
            recommendations.append("Consider reducing position sizes or diversifying")
        elif volatility < 0.05:
            recommendations.append("Portfolio is stable - consider increasing exposure")

        # Check Sharpe ratio
        if sharpe < 1.0:
            warnings.append(f"Sharpe ratio ({sharpe:.2f}) below 1.0 - insufficient risk-adjusted return")
        elif sharpe > 2.0:
            recommendations.append("Excellent risk-adjusted returns")

        # Check max drawdown
        if max_dd < -0.3:
            warnings.append(f"Max drawdown ({max_dd:.1%}) is severe")
            recommendations.append("Review stop losses and risk management")
        elif max_dd > -0.1:
            recommendations.append("Drawdown risk is well-controlled")

        # Check concentration
        if weights and max(weights) > 0.5:
            warnings.append("Portfolio is concentrated in top position")
            recommendations.append("Rebalance to reduce concentration risk")

        # Check position count
        if num_positions < 3:
            recommendations.append(f"Consider adding positions for diversification ({num_positions} current)")
        elif num_positions > 10:
            recommendations.append("Portfolio is diversified; monitor correlation drift")

        # Check total at risk
        if total_at_risk > self.portfolio_value * 0.1:
            warnings.append(f"Total at risk ({total_at_risk/self.portfolio_value:.1%}) exceeds 10%")
            recommendations.append("Reduce position sizes or tighten stops")

        # Determine risk level
        risk_score = (volatility * 100 + abs(max_dd) * 100 + 10 * num_positions) / 3
        
        if len(warnings) >= 3 or risk_score > 50:
            risk_level = "CRITICAL"
        elif len(warnings) >= 2 or risk_score > 30:
            risk_level = "HIGH"
        elif len(warnings) >= 1 or risk_score > 15:
            risk_level = "MEDIUM"
        else:
            risk_level = "LOW"

        return warnings, recommendations, risk_level

    def _calculate_risk_score(
        self,
        volatility: float,
        max_dd: float,
        num_positions: int,
        total_at_risk: float,
    ) -> float:
        """Calculate overall risk score (0-100)

        Args:
            volatility: Portfolio volatility
            max_dd: Max drawdown
            num_positions: Number of positions
            total_at_risk: Total $ at risk

        Returns:
            Risk score (0 = safest, 100 = riskiest)
        """
        vol_score = min(100, volatility * 200)  # 20% vol = 40 points
        dd_score = min(100, abs(max_dd) * 200)  # -20% dd = 40 points
        concentration_score = max(0, (10 - num_positions) * 5)  # Fewer positions = more risk
        
        # Average the three scores
        risk_score = (vol_score + dd_score + concentration_score) / 3

        return min(100, max(0, risk_score))

    def _generate_trade_reasoning(
        self,
        signal: str,
        risk_amount: Optional[float],
        reward_amount: Optional[float],
        max_portfolio_loss: float,
        adjusted_position: float,
    ) -> str:
        """Generate reasoning for trade risk assessment

        Args:
            signal: BUY, SELL, HOLD
            risk_amount: $ at risk
            reward_amount: $ potential gain
            max_portfolio_loss: % of portfolio at risk
            adjusted_position: Adjusted position size

        Returns:
            Reasoning string
        """
        if signal == "HOLD":
            return "No position risk - HOLD signal maintains current exposure"

        if not risk_amount or not reward_amount:
            return f"{signal} signal approved at {adjusted_position:.0%} position size"

        ratio_str = f"{reward_amount/risk_amount:.2f}:1" if risk_amount > 0 else "N/A"
        
        return (
            f"{signal} signal: Risk ${risk_amount:,.0f} for ${reward_amount:,.0f} ({ratio_str}). "
            f"Portfolio exposure: {max_portfolio_loss:.2%}. "
            f"Adjusted position: {adjusted_position:.0%} (risk-optimized)."
        )

    def _create_neutral_risk_metrics(self, trade_decision) -> RiskMetrics:
        """Create neutral risk metrics"""
        return RiskMetrics(
            trade_signal=trade_decision.signal,
            position_size=trade_decision.position_size,
            entry_price=trade_decision.entry_price,
            stop_loss=trade_decision.stop_loss,
            take_profit=trade_decision.take_profit,
            risk_amount=None,
            reward_amount=None,
            risk_reward_ratio=0.0,
            loss_percentage=None,
            gain_percentage=None,
            adjusted_position_size=trade_decision.position_size,
            max_portfolio_loss=0.0,
            reasoning="Insufficient market data for risk assessment",
            timestamp=datetime.utcnow().isoformat(),
        )

    def _create_error_risk_metrics(self, error: str) -> RiskMetrics:
        """Create error risk metrics"""
        return RiskMetrics(
            trade_signal="HOLD",
            position_size=0.0,
            entry_price=None,
            stop_loss=None,
            take_profit=None,
            risk_amount=None,
            reward_amount=None,
            risk_reward_ratio=0.0,
            loss_percentage=None,
            gain_percentage=None,
            adjusted_position_size=0.0,
            max_portfolio_loss=0.0,
            reasoning=f"Risk assessment error: {error}",
            timestamp=datetime.utcnow().isoformat(),
        )

    def _create_empty_portfolio_report(self) -> PortfolioRiskReport:
        """Create empty portfolio report"""
        return PortfolioRiskReport(
            total_portfolio_value=0.0,
            num_positions=0,
            portfolio_volatility=0.0,
            sharpe_ratio=0.0,
            sortino_ratio=0.0,
            max_drawdown=0.0,
            total_at_risk=0.0,
            portfolio_beta=1.0,
            correlation_matrix={},
            warnings=["No positions in portfolio"],
            recommendations=["Add positions to begin trading"],
            overall_risk_level="LOW",
            risk_score=0.0,
            timestamp=datetime.utcnow().isoformat(),
        )

    def _create_error_portfolio_report(self, error: str) -> PortfolioRiskReport:
        """Create error portfolio report"""
        return PortfolioRiskReport(
            total_portfolio_value=0.0,
            num_positions=0,
            portfolio_volatility=0.0,
            sharpe_ratio=0.0,
            sortino_ratio=0.0,
            max_drawdown=0.0,
            total_at_risk=0.0,
            portfolio_beta=1.0,
            correlation_matrix={},
            warnings=[f"Error: {error}"],
            recommendations=["Contact support"],
            overall_risk_level="UNKNOWN",
            risk_score=50.0,
            timestamp=datetime.utcnow().isoformat(),
        )
