"""Portfolio Manager - Manages multi-asset portfolio with rebalancing logic"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from decimal import Decimal

from cryptoagents.dataflows import NansenAPI, CoinGeckoAPI

logger = logging.getLogger(__name__)


@dataclass
class PortfolioHolding:
    """Individual asset holding in portfolio"""
    symbol: str
    amount: float
    current_price: float
    value_usd: float = 0.0
    percentage_of_portfolio: float = 0.0
    network: str = "ethereum"
    token_address: Optional[str] = None
    
    def __post_init__(self):
        """Calculate USD value"""
        self.value_usd = self.amount * self.current_price


@dataclass
class PortfolioState:
    """Current state of entire portfolio"""
    total_value_usd: float
    holdings: Dict[str, PortfolioHolding] = field(default_factory=dict)
    stablecoin_value: float = 0.0
    stablecoin_percentage: float = 0.0
    liquid_value: float = 0.0  # Non-stablecoin value
    cash_available: float = 0.0
    last_updated: str = ""
    
    def get_allocation_by_symbol(self, symbol: str) -> float:
        """Get portfolio percentage for a symbol"""
        if symbol in self.holdings:
            return self.holdings[symbol].percentage_of_portfolio
        return 0.0
    
    def get_asset_value(self, symbol: str) -> float:
        """Get USD value for a symbol"""
        if symbol in self.holdings:
            return self.holdings[symbol].value_usd
        return 0.0


@dataclass
class RebalanceRecommendation:
    """Recommendation to rebalance portfolio"""
    symbol: str
    current_allocation: float  # Current portfolio %
    target_allocation: float  # Target portfolio %
    action: str  # BUY, SELL, or HOLD
    amount_usd: float  # USD amount to buy/sell
    amount_tokens: float  # Number of tokens to buy/sell
    urgency: str  # LOW, MEDIUM, HIGH
    reasoning: str
    signal_strength: float  # From trader agent (-1 to 1)
    confidence: float
    
    @property
    def requires_action(self) -> bool:
        """Check if this recommendation requires action"""
        return self.action != "HOLD" and abs(self.amount_usd) > 10.0  # Minimum $10


class PortfolioManager:
    """Manages multi-asset cryptocurrency portfolio with Nansen integration"""
    
    def __init__(
        self,
        nansen_api: NansenAPI,
        coingecko_api: CoinGeckoAPI,
        wallet_addresses: Dict[str, str],
        stable_coin_reserve: float = 0.30,
        max_allocation_per_asset: float = 0.15,
        portfolio_value: float = 100000.0,
        hyperliquid_trader: Optional[Any] = None
    ):
        """
        Initialize Portfolio Manager
        
        Args:
            nansen_api: NansenAPI instance for wallet queries
            coingecko_api: CoinGeckoAPI instance for price data
            wallet_addresses: Dict of {network: wallet_address}
                e.g., {"hyperliquid": "0x...", "solana": "..."}
            stable_coin_reserve: Percentage to keep in stablecoins (default 30%)
            max_allocation_per_asset: Max allocation per non-stable asset (default 15%)
            portfolio_value: Initial portfolio value in USD
            hyperliquid_trader: Optional live HyperliquidTrader for real account/position data
        """
        self.nansen_api = nansen_api
        self.coingecko_api = coingecko_api
        self.wallet_addresses = wallet_addresses
        self.stable_coin_reserve = stable_coin_reserve
        self.max_allocation_per_asset = max_allocation_per_asset
        self.initial_portfolio_value = portfolio_value
        self.hyperliquid_trader = hyperliquid_trader
        
        self.current_state: Optional[PortfolioState] = None
        self.holdings_history: List[PortfolioState] = []
        self.stablecoins = {"USDC", "USDT", "DAI", "BUSD", "TUSD", "USDP"}

        logger.info(f"PortfolioManager initialized")
        logger.info(f"  Wallets: {wallet_addresses}")
        logger.info(f"  Stablecoin reserve: {stable_coin_reserve:.0%}")
        logger.info(f"  Max allocation per asset: {max_allocation_per_asset:.0%}")

    def set_hyperliquid_trader(self, hyperliquid_trader: Any) -> None:
        """Attach a live HyperliquidTrader so fetch_holdings() uses real account data"""
        self.hyperliquid_trader = hyperliquid_trader
    
    def fetch_holdings(self) -> PortfolioState:
        """
        Fetch current holdings - live from Hyperliquid if connected, else simulated
        
        Returns:
            PortfolioState with current holdings
        """
        if self.hyperliquid_trader is not None:
            try:
                return self._fetch_holdings_from_hyperliquid()
            except Exception as e:
                logger.error(f"[WARN] Live Hyperliquid holdings fetch failed, falling back to simulated data: {e}")
        
        return self._fetch_simulated_holdings()

    def _fetch_holdings_from_hyperliquid(self) -> PortfolioState:
        """Build PortfolioState from live Hyperliquid account balance + open positions"""
        logger.info("Fetching portfolio holdings from Hyperliquid (live)...")

        balance_info = self.hyperliquid_trader.get_account_balance()
        if balance_info.get("error"):
            raise RuntimeError(balance_info["error"])

        free_collateral = float(balance_info.get("free_collateral", 0.0))
        holdings: Dict[str, PortfolioHolding] = {}
        stablecoin_value = free_collateral

        if free_collateral > 0:
            holdings["USDC"] = PortfolioHolding(
                symbol="USDC", amount=free_collateral, current_price=1.0, network="hyperliquid"
            )

        for pos in self.hyperliquid_trader.get_open_positions():
            holding = PortfolioHolding(
                symbol=pos.symbol,
                amount=pos.size,
                current_price=pos.current_price,
                network="hyperliquid",
            )
            # Margin at risk, not leveraged notional exposure
            holding.value_usd = pos.collateral_used
            holdings[pos.symbol] = holding

        total_value = sum(h.value_usd for h in holdings.values())

        for holding in holdings.values():
            holding.percentage_of_portfolio = holding.value_usd / total_value if total_value > 0 else 0

        state = PortfolioState(
            total_value_usd=total_value,
            holdings=holdings,
            stablecoin_value=stablecoin_value,
            stablecoin_percentage=stablecoin_value / total_value if total_value > 0 else 0,
            liquid_value=total_value - stablecoin_value,
            cash_available=stablecoin_value,
            last_updated=datetime.now(timezone.utc).isoformat(),
        )

        self.current_state = state
        self.holdings_history.append(state)

        logger.info(f"Portfolio holdings fetched (live):")
        logger.info(f"  Total Value: ${total_value:,.2f}")
        logger.info(f"  Free Collateral: ${free_collateral:,.2f}")
        logger.info(f"  Open Positions: {len(holdings) - (1 if free_collateral > 0 else 0)}")

        return state

    def _fetch_simulated_holdings(self) -> PortfolioState:
        """Fallback holdings used when no live Hyperliquid trader is attached"""
        holdings = {}
        total_value = 0.0
        stablecoin_value = 0.0
        
        logger.info("Fetching portfolio holdings (simulated - no live trader attached)...")
        
        # Simulated holdings for demo
        simulated_holdings = {
            "BTC": {"amount": 0.5, "price": 77990, "network": "hyperliquid"},
            "ETH": {"amount": 5.0, "price": 2456, "network": "hyperliquid"},
            "USDC": {"amount": 15000.0, "price": 1.0, "network": "hyperliquid"},
            "SOL": {"amount": 50.0, "price": 142, "network": "solana"},
        }
        
        # Convert to PortfolioHolding objects
        for symbol, data in simulated_holdings.items():
            holding = PortfolioHolding(
                symbol=symbol,
                amount=data["amount"],
                current_price=data["price"],
                network=data["network"]
            )
            
            holdings[symbol] = holding
            total_value += holding.value_usd
            
            # Track stablecoins separately
            if symbol in self.stablecoins:
                stablecoin_value += holding.value_usd
        
        # Calculate percentages
        for symbol, holding in holdings.items():
            holding.percentage_of_portfolio = holding.value_usd / total_value if total_value > 0 else 0
        
        # Create portfolio state
        state = PortfolioState(
            total_value_usd=total_value,
            holdings=holdings,
            stablecoin_value=stablecoin_value,
            stablecoin_percentage=stablecoin_value / total_value if total_value > 0 else 0,
            liquid_value=total_value - stablecoin_value,
            cash_available=stablecoin_value,
            last_updated=datetime.now(timezone.utc).isoformat()
        )
        
        self.current_state = state
        self.holdings_history.append(state)
        
        logger.info(f"Portfolio holdings fetched:")
        logger.info(f"  Total Value: ${total_value:,.2f}")
        logger.info(f"  Stablecoins: ${stablecoin_value:,.2f} ({stablecoin_value/total_value:.1%})")
        logger.info(f"  Active Positions: {len([h for h in holdings.values() if h.symbol not in self.stablecoins])}")
        
        return state
    
    def make_rebalance_recommendations(
        self,
        trade_decisions: Dict[str, Tuple[str, float, float]]  # {symbol: (signal, confidence, score)}
    ) -> List[RebalanceRecommendation]:
        """
        Make rebalancing recommendations based on trader signals
        
        Args:
            trade_decisions: Dict of {symbol: (signal, confidence, score)}
                signal: "BUY", "SELL", "HOLD"
                confidence: 0-1
                score: -1 to 1
        
        Returns:
            List of rebalancing recommendations
        """
        if not self.current_state:
            self.fetch_holdings()
        
        recommendations = []
        logger.info("\nGenerating rebalancing recommendations...")
        
        # Calculate allocations for liquid (non-stablecoin) assets
        liquid_value = self.current_state.liquid_value
        if liquid_value <= 0:
            logger.warning("No liquid assets to allocate")
            return recommendations
        
        # Process each trade decision
        for symbol, (signal, confidence, score) in trade_decisions.items():
            current_allocation = self.current_state.get_allocation_by_symbol(symbol)
            current_value = self.current_state.get_asset_value(symbol)
            
            # Calculate target allocation based on signal strength
            if signal == "BUY":
                # Buy strength based on score and confidence
                # Score range: -1 to 1, we map to allocation range
                allocation_boost = (score + 1) / 2 * confidence  # 0 to 1 scaled
                target_allocation = min(
                    self.max_allocation_per_asset * (0.5 + allocation_boost),
                    self.max_allocation_per_asset
                )
            elif signal == "SELL":
                # Reduce or exit position
                target_allocation = current_allocation * (1 - confidence * 0.5)
            else:  # HOLD
                # Maintain current allocation
                target_allocation = current_allocation
            
            # Calculate difference
            allocation_diff = target_allocation - current_allocation
            
            # Determine action and amount
            if allocation_diff > 0.01:  # Buy if difference > 1%
                action = "BUY"
                urgency = "HIGH" if allocation_diff > 0.05 else "MEDIUM"
                amount_usd = allocation_diff * self.current_state.total_value_usd
            elif allocation_diff < -0.01:  # Sell if difference > 1%
                action = "SELL"
                urgency = "HIGH" if abs(allocation_diff) > 0.05 else "MEDIUM"
                amount_usd = abs(allocation_diff) * self.current_state.total_value_usd
            else:
                action = "HOLD"
                urgency = "LOW"
                amount_usd = 0.0
            
            # Get current price for token amount calculation
            if symbol in self.current_state.holdings:
                price = self.current_state.holdings[symbol].current_price
                amount_tokens = amount_usd / price if price > 0 else 0
            else:
                amount_tokens = 0
            
            # Create recommendation
            rec = RebalanceRecommendation(
                symbol=symbol,
                current_allocation=current_allocation,
                target_allocation=target_allocation,
                action=action,
                amount_usd=amount_usd,
                amount_tokens=amount_tokens,
                urgency=urgency,
                reasoning=f"{signal} signal ({score:+.2f}) → target {target_allocation:.1%} vs current {current_allocation:.1%}",
                signal_strength=score,
                confidence=confidence
            )
            
            recommendations.append(rec)
            
            if rec.requires_action:
                logger.info(f"  {symbol}: {action} {abs(amount_usd):,.2f} USD ({abs(amount_tokens):.4f} tokens)")
        
        # Add stablecoin management
        current_stable_pct = self.current_state.stablecoin_percentage
        if current_stable_pct < self.stable_coin_reserve * 0.9:  # Below reserve by 10%
            # Need to buy more stables
            needed_stable_value = (self.stable_coin_reserve - current_stable_pct) * self.current_state.total_value_usd
            logger.info(f"  USDC: BUY {needed_stable_value:,.2f} USD (maintain reserve)")
        elif current_stable_pct > self.stable_coin_reserve * 1.1:  # Above reserve by 10%
            # Can sell excess stables
            excess_stable_value = (current_stable_pct - self.stable_coin_reserve) * self.current_state.total_value_usd
            logger.info(f"  USDC: SELL {excess_stable_value:,.2f} USD (trim excess)")
        
        return recommendations
    
    def calculate_portfolio_metrics(self) -> Dict[str, float]:
        """
        Calculate portfolio-wide metrics
        
        Returns:
            Dict with portfolio metrics
        """
        if not self.current_state:
            self.fetch_holdings()
        
        # Calculate concentration (Herfindahl index)
        concentration = sum(h.percentage_of_portfolio ** 2 for h in self.current_state.holdings.values())
        
        # Count assets
        num_active_assets = len([h for h in self.current_state.holdings.values() 
                                if h.symbol not in self.stablecoins])
        
        # Diversification score (1 - concentration), scaled to 0-100
        diversification = (1 - concentration) * 100
        
        metrics = {
            "total_value": self.current_state.total_value_usd,
            "stablecoin_value": self.current_state.stablecoin_value,
            "stablecoin_percentage": self.current_state.stablecoin_percentage,
            "liquid_value": self.current_state.liquid_value,
            "num_active_assets": num_active_assets,
            "concentration_index": concentration,
            "diversification_score": diversification,
            "largest_position": max([h.percentage_of_portfolio for h in self.current_state.holdings.values()],
                                   default=0),
            "cash_available": self.current_state.cash_available,
        }
        
        logger.info("Portfolio Metrics:")
        logger.info(f"  Total Value: ${metrics['total_value']:,.2f}")
        logger.info(f"  Stablecoin Reserve: {metrics['stablecoin_percentage']:.1%}")
        logger.info(f"  Active Assets: {metrics['num_active_assets']}")
        logger.info(f"  Diversification Score: {metrics['diversification_score']:.1f}/100")
        logger.info(f"  Largest Position: {metrics['largest_position']:.1%}")
        
        return metrics
    
    def get_portfolio_summary(self) -> Dict:
        """Get complete portfolio summary for display"""
        if not self.current_state:
            self.fetch_holdings()
        
        holdings_summary = []
        for symbol, holding in sorted(
            self.current_state.holdings.items(),
            key=lambda x: x[1].value_usd,
            reverse=True
        ):
            holdings_summary.append({
                "symbol": symbol,
                "amount": holding.amount,
                "price": holding.current_price,
                "value_usd": holding.value_usd,
                "allocation": holding.percentage_of_portfolio,
                "network": holding.network,
            })
        
        return {
            "timestamp": self.current_state.last_updated,
            "total_value": self.current_state.total_value_usd,
            "holdings": holdings_summary,
            "stablecoin_reserve": self.current_state.stablecoin_percentage,
            "cash_available": self.current_state.cash_available,
            "num_holdings": len(self.current_state.holdings),
        }
