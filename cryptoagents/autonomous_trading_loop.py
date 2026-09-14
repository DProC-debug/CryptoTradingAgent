"""
Autonomous Trading Loop
Continuously executes trading cycles without manual intervention
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import List, Optional
from dotenv import load_dotenv

from cryptoagents.graph.trading_graph import CryptoTradingGraph
from cryptoagents.utilities.coin_selector import CoinSelector
from cryptoagents.dataflows.coingecko_api import CoinGeckoAPI
from cryptoagents.dataflows.nansen_api import NansenAPI
from cryptoagents.exchanges.hyperliquid_trader import HyperliquidTrader
from cryptoagents.exchanges.nansen_perp_trader import NansenPerpTrader

load_dotenv()
logger = logging.getLogger(__name__)


class TradeRecord:
    """Record of a single trade execution"""
    def __init__(self, symbol, signal, confidence, entry_price, leverage):
        self.symbol = symbol
        self.signal = signal
        self.confidence = confidence
        self.entry_price = entry_price
        self.leverage = leverage
        self.timestamp = datetime.now()
        self.status = "OPEN"
        self.exit_price = None
        self.pnl = None
        self.pnl_percentage = None
    
    def to_dict(self):
        return {
            "symbol": self.symbol,
            "signal": self.signal,
            "confidence": f"{self.confidence * 100:.1f}%",
            "entry_price": f"${self.entry_price:.6f}",
            "leverage": f"{self.leverage:.1f}x",
            "timestamp": self.timestamp.isoformat(),
            "status": self.status,
            "exit_price": f"${self.exit_price:.6f}" if self.exit_price else "N/A",
            "pnl": f"${self.pnl:.2f}" if self.pnl else "N/A",
            "pnl_percentage": f"{self.pnl_percentage * 100:.1f}%" if self.pnl_percentage else "N/A"
        }

    def to_state(self):
        """Serialize with raw types (not display-formatted) for crash-safe persistence"""
        return {
            "symbol": self.symbol,
            "signal": self.signal,
            "confidence": self.confidence,
            "entry_price": self.entry_price,
            "leverage": self.leverage,
            "timestamp": self.timestamp.isoformat(),
            "status": self.status,
            "exit_price": self.exit_price,
            "pnl": self.pnl,
            "pnl_percentage": self.pnl_percentage,
        }

    @classmethod
    def from_state(cls, data: dict) -> "TradeRecord":
        record = cls(
            symbol=data["symbol"],
            signal=data["signal"],
            confidence=data["confidence"],
            entry_price=data["entry_price"],
            leverage=data["leverage"],
        )
        record.timestamp = datetime.fromisoformat(data["timestamp"])
        record.status = data["status"]
        record.exit_price = data.get("exit_price")
        record.pnl = data.get("pnl")
        record.pnl_percentage = data.get("pnl_percentage")
        return record


class AutonomousTrader:
    """
    Autonomous trading agent that runs continuously
    Executes trading cycles and monitors positions
    """
    
    def __init__(self):
        """Initialize autonomous trader with all required components"""
        logger.info("[START] Initializing AutonomousTrader...")
        
        # Configuration
        self.trading_enabled = os.getenv("HYPERLIQUID_TRADING_ENABLED", "false").lower() == "true"
        self.execution_interval_minutes = int(os.getenv("HYPERLIQUID_EXECUTION_INTERVAL_MINUTES", "60"))
        self.monitoring_interval_seconds = int(os.getenv("HYPERLIQUID_MONITORING_INTERVAL_SECONDS", "300"))
        self.max_concurrent_positions = int(os.getenv("HYPERLIQUID_MAX_CONCURRENT_POSITIONS", "3"))
        # Correlation proxy: real historical-correlation data isn't available for arbitrary
        # altcoins here, so this caps concurrent exposure to the same CoinGecko sector/category
        # tag instead (e.g. "Layer 1 (L1)", "Meme", "DeFi") to avoid 5 "different" positions
        # that are really one correlated bet.
        self.max_positions_per_category = int(os.getenv("HYPERLIQUID_MAX_POSITIONS_PER_CATEGORY", "2"))
        self.max_daily_trades = int(os.getenv("HYPERLIQUID_MAX_DAILY_TRADES", "10"))
        self.max_daily_loss_pct = float(os.getenv("HYPERLIQUID_MAX_DAILY_LOSS_PCT", "0.05"))
        self.position_size_usd = float(os.getenv("HYPERLIQUID_POSITION_SIZE_USD", "50"))
        # Raw price-move percentages (NOT leveraged ROE) - see monitor_positions().
        # Defaults are asymmetric (2:1 reward:risk) and both comfortably clear the slippage
        # tolerance below, so typical execution cost can't eat the whole target/stop.
        self.take_profit_pct = float(os.getenv("HYPERLIQUID_TAKE_PROFIT_PCT", "0.12"))
        self.stop_loss_pct = float(os.getenv("HYPERLIQUID_STOP_LOSS_PCT", "-0.06"))
        self.max_leverage = int(os.getenv("HYPERLIQUID_MAX_LEVERAGE", "20"))
        self.slippage = float(os.getenv("HYPERLIQUID_SLIPPAGE", "0.03"))
        self.order_type = os.getenv("HYPERLIQUID_ORDER_TYPE", "market")
        self.coin_selection_weight = os.getenv("HYPERLIQUID_COIN_SELECTION_WEIGHT", "liquidity")
        self.coins_per_cycle = int(os.getenv("HYPERLIQUID_COINS_PER_CYCLE", "5"))
        self.exclude_coins = [
            s.strip().upper()
            for s in os.getenv("HYPERLIQUID_EXCLUDE_COINS", "BTC,ETH,USDT,USDC,BUSD,DAI").split(",")
            if s.strip()
        ]
        
        # Wallet configuration
        self.wallet_address = os.getenv("PORTFOLIO_WALLET_HYPERLIQUID", "")
        self.nansen_api_key = os.getenv("NANSEN_API_KEY", "")
        self.wallet_private_key = os.getenv("PORTFOLIO_WALLET_PRIVATE_KEY", "")
        # "nansen" routes execution through Nansen's perp API; "hyperliquid_sdk" uses the official SDK directly
        self.trading_backend = os.getenv("TRADING_BACKEND", "nansen").lower()
        
        # Trading state
        self.trades_today: List[TradeRecord] = []
        self.is_running = False
        self.cycle_count = 0
        self.current_day = datetime.now().date()
        self.daily_starting_balance: Optional[float] = None
        
        # Initialize APIs
        logger.info("[INIT] Initializing APIs...")
        self.coingecko_api = CoinGeckoAPI(api_key=os.getenv("COINGECKO_API_KEY") or None)
        # NansenAPI() raises if given an empty key, so only construct it when one is actually set;
        # CoinSelector falls back to liquidity weighting if nansen_api is None
        coin_selector_nansen = NansenAPI(self.nansen_api_key) if self.nansen_api_key else None
        self.coin_selector = CoinSelector(self.coingecko_api, exclude_symbols=self.exclude_coins, nansen_api=coin_selector_nansen)
        self.trading_graph = CryptoTradingGraph(debug=False)
        self.hyperliquid_trader = None

        # Crash-safe state: survive a process restart without losing today's trade/loss
        # bookkeeping. Real open positions are always re-fetched live from the exchange, so
        # only this in-memory accounting needs persisting.
        self.state_file = os.path.join(self.trading_graph.config["data_cache_dir"], "autonomous_trader_state.json")
        self._load_state()

        logger.info(f"[OK] AutonomousTrader initialized")
        logger.info(f"   Trading enabled: {self.trading_enabled}")
        logger.info(f"   Trading backend: {self.trading_backend}")
        logger.info(f"   Execution interval: {self.execution_interval_minutes} minutes")
        logger.info(f"   Monitoring interval: {self.monitoring_interval_seconds} seconds")
        logger.info(f"   Position size: ${self.position_size_usd}")
    
    def initialize_trader(self):
        """Initialize the trading backend (Nansen-routed perp API, or the official Hyperliquid SDK directly)"""
        if not self.wallet_address:
            logger.error("[ERROR] Missing PORTFOLIO_WALLET_HYPERLIQUID in .env")
            return False
        
        if not self.wallet_private_key:
            logger.error("[ERROR] Missing PORTFOLIO_WALLET_PRIVATE_KEY - trading will be disabled")
            logger.error("[ERROR] Add wallet private key to .env to enable trade execution")
            return False
        
        try:
            if self.trading_backend == "nansen":
                if not self.nansen_api_key:
                    logger.error("[ERROR] Missing NANSEN_API_KEY - required for TRADING_BACKEND=nansen")
                    return False
                self.hyperliquid_trader = NansenPerpTrader(
                    api_key=self.nansen_api_key,
                    wallet_address=self.wallet_address,
                    wallet_private_key=self.wallet_private_key,
                    max_leverage=self.max_leverage
                )
                logger.info(f"[OK] Nansen perp trader initialized (routes to Hyperliquid)")
            else:
                # Official SDK initialization (synchronous)
                self.hyperliquid_trader = HyperliquidTrader(
                    wallet_address=self.wallet_address,
                    wallet_private_key=self.wallet_private_key,
                    max_leverage=self.max_leverage
                )
                logger.info(f"[OK] Hyperliquid trader initialized with official SDK")
            # Feed real account/position data into the portfolio manager
            self.trading_graph.portfolio_manager.set_hyperliquid_trader(self.hyperliquid_trader)
            logger.info(f"    Wallet: {self.wallet_address[:10]}...")
            return True
        except Exception as e:
            logger.error(f"[ERROR] Failed to initialize {self.trading_backend} trader: {e}")
            return False
    
    def _load_state(self):
        """Restore trades_today/daily_starting_balance/cycle_count if today's state was
        persisted (e.g. after a crash/restart). Discards anything from a previous day -
        _roll_over_day_if_needed() handles the same reset during a long-running process."""
        try:
            if not os.path.exists(self.state_file):
                return
            with open(self.state_file, "r") as f:
                data = json.load(f)
            if data.get("date") != self.current_day.isoformat():
                logger.info(f"[STATE] Discarding persisted state from {data.get('date')} (today is {self.current_day})")
                return
            self.trades_today = [TradeRecord.from_state(t) for t in data.get("trades_today", [])]
            self.daily_starting_balance = data.get("daily_starting_balance")
            self.cycle_count = data.get("cycle_count", 0)
            logger.info(f"[STATE] Restored {len(self.trades_today)} trade(s) from today's persisted state")
        except Exception as e:
            logger.warning(f"[WARN] Could not load persisted state, starting fresh: {e}")

    def _save_state(self):
        """Persist trades_today/daily_starting_balance/cycle_count so a crash/restart doesn't
        lose today's bookkeeping. Real open positions are always re-fetched live from the
        exchange, so only this in-memory accounting needs saving. Written atomically (temp
        file + rename) so a crash mid-write can't corrupt the existing file."""
        try:
            os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
            data = {
                "date": self.current_day.isoformat(),
                "daily_starting_balance": self.daily_starting_balance,
                "cycle_count": self.cycle_count,
                "trades_today": [t.to_state() for t in self.trades_today],
            }
            tmp_path = self.state_file + ".tmp"
            with open(tmp_path, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp_path, self.state_file)
        except Exception as e:
            logger.warning(f"[WARN] Could not persist state: {e}")

    def _get_coin_categories(self, symbol: str) -> set:
        """Fetch CoinGecko sector/category tags for a symbol (correlation proxy - see
        max_positions_per_category). Fails open (returns an empty set) on any error so a
        CoinGecko hiccup can't block trading entirely, only skip this one check."""
        try:
            coin_id = self.coingecko_api.resolve_coin_id(symbol)
            if not coin_id:
                return set()
            details = self.coingecko_api.get_coin_details(coin_id)
            return {c for c in (details.get("categories") or []) if c}
        except Exception as e:
            logger.warning(f"[WARN] Could not fetch categories for {symbol}: {e}")
            return set()

    def _roll_over_day_if_needed(self):
        """Reset daily counters (trade count, loss-breaker baseline) at each real calendar day boundary"""
        today = datetime.now().date()
        if today != self.current_day:
            logger.info(f"[NEW DAY] Rolling over from {self.current_day} to {today} - resetting daily counters")
            self.current_day = today
            self.trades_today = []
            self.daily_starting_balance = None
            self._save_state()

    def _within_daily_loss_limit(self) -> bool:
        """Daily P&L circuit breaker.

        Halts new entries (not position monitoring - TP/SL closes still run) once today's
        loss crosses max_daily_loss_pct of the day's starting balance. Compares the live
        account balance directly against the day's starting baseline, rather than manually
        summing closed-trade P&L + live unrealized P&L - Hyperliquid's accountValue is total
        mark-to-market equity (collateral + unrealized P&L on open positions), and moves in
        real time as funding gets settled. A manual sum misses funding entirely (neither
        closed-trade P&L nor unrealized_pnl includes it), so a position quietly bleeding
        funding fees all day wouldn't trip the breaker even as the account actually drains.
        Comparing live balance to the baseline directly captures everything that actually
        moves the account - trade P&L, funding, all of it - with no risk of double-counting.
        Resets automatically at the next day rollover.
        """
        balance_info = self.hyperliquid_trader.get_account_balance()
        if balance_info.get("error"):
            logger.warning(f"[WARN] Could not check daily loss limit: {balance_info.get('error')}")
            return True  # fail open - a balance-check hiccup shouldn't itself halt trading

        current_balance = balance_info.get("total_collateral", 0)

        if self.daily_starting_balance is None:
            self.daily_starting_balance = current_balance
            logger.info(f"[DAY START] Baseline balance for loss limit: ${self.daily_starting_balance:,.2f}")
            self._save_state()

        if not self.daily_starting_balance:
            return True  # nothing meaningful to compare against

        day_pnl_pct = (current_balance - self.daily_starting_balance) / self.daily_starting_balance

        if day_pnl_pct <= -self.max_daily_loss_pct:
            logger.warning(
                f"[CIRCUIT BREAKER] Daily loss limit hit: {day_pnl_pct:+.2%} "
                f"(limit -{self.max_daily_loss_pct:.0%}) - halting new trades until tomorrow"
            )
            return False

        return True

    async def execute_trading_cycle(self):
        """Execute one complete trading cycle: select, analyze, execute"""
        self.cycle_count += 1
        logger.info(f"\n{'='*70}")
        logger.info(f"[CYCLE] #{self.cycle_count} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"{'='*70}")

        try:
            self._roll_over_day_if_needed()

            # Step 1: Fetch open positions once - needed for the loss breaker, the concurrent
            # position limit, and to avoid re-entering a coin we already hold
            open_positions = []
            open_symbols = set()
            if self.hyperliquid_trader:
                open_positions = self.hyperliquid_trader.get_open_positions()
                open_symbols = {p.symbol for p in open_positions}
            # Simulated trades never touch the exchange, so track their "OPEN" status separately
            open_symbols |= {t.symbol for t in self.trades_today if t.status == "OPEN"}

            # Category exposure of currently open positions (correlation proxy - see
            # _get_coin_categories); updated live below as new candidates get accepted
            category_counts: dict = {}
            for sym in open_symbols:
                for cat in self._get_coin_categories(sym):
                    category_counts[cat] = category_counts.get(cat, 0) + 1

            # Step 2: Daily loss circuit breaker - stop opening new trades, existing positions
            # still get monitored/closed normally
            if self.hyperliquid_trader and not self._within_daily_loss_limit():
                return

            # Step 3: Check daily trade limit
            if len(self.trades_today) >= self.max_daily_trades:
                logger.warning(f"[WARN] Daily trade limit reached ({self.max_daily_trades} trades)")
                return

            # Step 4: Check concurrent position limit
            if self.hyperliquid_trader and len(open_positions) >= self.max_concurrent_positions:
                logger.warning(f"[WARN] Max concurrent positions reached ({len(open_positions)}/{self.max_concurrent_positions})")
                return

            # Step 5: Select a batch of coins for the cycle
            logger.info(f"\n[STEP 1] Selecting {self.coins_per_cycle} altcoins for batch analysis...")
            market_data = self.coingecko_api.get_market_data(per_page=250, page=1)
            candidate_coins = await self.coin_selector.select_n_random_coins(
                n=self.coins_per_cycle, market_data=market_data, weights=self.coin_selection_weight
            )
            
            if not candidate_coins:
                logger.error("[ERROR] Failed to select candidate coins")
                return
            
            logger.info(f"[OK] Evaluating {len(candidate_coins)} coins in this batch")
            for coin in candidate_coins:
                logger.info(f"   - {coin.symbol}: ${coin.current_price:.6f} (Vol: ${coin.volume_24h_usd:,.0f})")

            actionable_trades = []

            # Step 6: Analyze each coin in the batch
            for coin in candidate_coins:
                if coin.symbol in open_symbols:
                    logger.info(f"[SKIP] {coin.symbol} already has an open position - skipping re-entry")
                    continue

                logger.info(f"\n[STEP 2] Analyzing {coin.symbol}...")
                success, analysis = await self.trading_graph.propagate(coin.symbol, None)
                
                if not success:
                    logger.warning(f"[WARN] Analysis failed for {coin.symbol}")
                    continue
                
                signal = analysis.get("signal", "HOLD")
                confidence = analysis.get("confidence", 0.0)
                entry_price = analysis.get("entry_price")
                
                logger.info(f"[OK] Analysis complete")
                logger.info(f"   Signal: {signal}")
                logger.info(f"   Confidence: {confidence * 100:.1f}%")
                if entry_price:
                    logger.info(f"   Suggested Entry: ${entry_price:.6f}")
                
                if signal in ("BUY", "SELL"):
                    candidate_categories = self._get_coin_categories(coin.symbol)
                    over_exposed = [
                        cat for cat in candidate_categories
                        if category_counts.get(cat, 0) >= self.max_positions_per_category
                    ]
                    if over_exposed:
                        logger.info(
                            f"[SKIP] {coin.symbol} rejected: already at max "
                            f"({self.max_positions_per_category}) positions in category {over_exposed}"
                        )
                        continue

                    # Execute BUY/SELL signals regardless of confidence
                    logger.info(f"[ACTION] Candidate trade identified: {coin.symbol} {signal} @ {confidence * 100:.1f}%")
                    actionable_trades.append({
                        "coin": coin,
                        "signal": signal,
                        "confidence": confidence,
                        "entry_price": entry_price or coin.current_price,
                        # Risk manager's 0-1 fraction of the configured base position size
                        # (already accounts for portfolio-risk-limit and confidence scaling)
                        "position_size_fraction": min(1.0, max(0.0, analysis.get("position_size", 1.0)))
                    })
                    # Count this accepted candidate immediately so a second correlated pick
                    # in the same batch is also caught, not just already-open positions
                    for cat in candidate_categories:
                        category_counts[cat] = category_counts.get(cat, 0) + 1
                else:
                    logger.info(f"[SKIP] {coin.symbol} rejected: signal={signal}, confidence={confidence * 100:.1f}%")

            # Step 7: Make trading decision for the batch
            logger.info(f"\n[STEP 3] Evaluating batch results...")
            if not actionable_trades:
                logger.info(f"[SKIP] No actionable BUY/SELL signals in this {self.coins_per_cycle}-coin batch")
                logger.info(f"   Waiting {self.execution_interval_minutes} minutes before next cycle")
                return

            for trade_candidate in actionable_trades:
                coin = trade_candidate["coin"]
                signal = trade_candidate["signal"]
                confidence = trade_candidate["confidence"]
                entry_price = trade_candidate["entry_price"]
                size_fraction = trade_candidate["position_size_fraction"]
                position_size_usd = self.position_size_usd * size_fraction

                if not self.trading_enabled:
                    logger.info(f"[INFO] HYPERLIQUID_TRADING_ENABLED=false")
                    logger.info(f"   Simulating trade for {coin.symbol}: {signal} @ {confidence * 100:.1f}%")
                    self._log_simulated_trade(coin.symbol, signal, confidence, entry_price, position_size_usd)
                    continue

                logger.info(f"\n[STEP 4] Executing {signal} order for {coin.symbol}...")
                leverage = min(confidence * self.max_leverage, self.max_leverage)
                is_buy = signal == "BUY"

                logger.info(f"   Order Direction: {'BUY' if is_buy else 'SELL'}")
                logger.info(f"   Position Size: ${position_size_usd:.2f} (base ${self.position_size_usd} x risk-adjusted {size_fraction:.0%})")
                logger.info(f"   Leverage: {leverage:.1f}x (confidence-scaled)")
                logger.info(f"   Entry Price: ${coin.current_price:.6f}")

                # Leverage must be set explicitly before the order - placing an order doesn't change it
                if hasattr(self.hyperliquid_trader, "set_leverage"):
                    try:
                        self.hyperliquid_trader.set_leverage(coin.symbol, max(1, round(leverage)), is_cross=False)
                    except Exception as e:
                        logger.warning(f"[WARN] Could not set leverage for {coin.symbol}, proceeding with existing setting: {e}")

                # Official SDK methods are synchronous (no await)
                order_result = self.hyperliquid_trader.open_position(
                    symbol=coin.symbol,
                    is_buy=is_buy,
                    size_usd=position_size_usd,
                    leverage=leverage,
                    slippage=self.slippage,
                    price=coin.current_price,
                    order_type=self.order_type
                )

                if order_result.success:
                    logger.info(f"[SUCCESS] ORDER PLACED")
                    logger.info(f"   Position ID: {order_result.position_id}")
                    logger.info(f"   Entry Price: ${order_result.entry_price:.6f}")

                    trade = TradeRecord(
                        symbol=coin.symbol,
                        signal=signal,
                        confidence=confidence,
                        entry_price=order_result.entry_price,
                        leverage=leverage
                    )
                    self.trades_today.append(trade)
                    self._save_state()
                    logger.info(f"   Trade #{len(self.trades_today)} recorded")
                else:
                    logger.error(f"[ERROR] ORDER FAILED for {coin.symbol}: {order_result.error}")

                # Respect the daily and concurrent position limits before continuing to next coin in batch
                if len(self.trades_today) >= self.max_daily_trades:
                    logger.warning(f"[WARN] Daily trade limit reached ({self.max_daily_trades})")
                    break
                if self.hyperliquid_trader and len(self.hyperliquid_trader.get_open_positions()) >= self.max_concurrent_positions:
                    logger.warning(f"[WARN] Max concurrent positions reached ({self.max_concurrent_positions})")
                    break
        
        except Exception as e:
            logger.error(f"[ERROR] Trading cycle failed: {e}", exc_info=True)
    
    def _log_simulated_trade(self, symbol, signal, confidence, entry_price, position_size_usd=None):
        """Log a simulated trade (when trading disabled)"""
        if position_size_usd is None:
            position_size_usd = self.position_size_usd
        logger.info(f"[DEMO] SIMULATED TRADE:")
        logger.info(f"   Symbol: {symbol}")
        logger.info(f"   Signal: {signal}")
        logger.info(f"   Confidence: {confidence * 100:.1f}%")
        leverage = min(confidence * self.max_leverage, self.max_leverage)
        logger.info(f"   Would execute: {signal} ${position_size_usd:.2f} @ {leverage:.1f}x leverage")
        logger.info(f"   Entry Price: ${entry_price:.6f}")
        
        # Still record for statistics
        trade = TradeRecord(symbol, signal, confidence, entry_price, leverage)
        self.trades_today.append(trade)
        self._save_state()

    async def monitor_positions(self):
        """Background task: Monitor positions and auto-close on take-profit/stop-loss"""
        if not self.hyperliquid_trader:
            return
        
        logger.info("\n[MONITOR] Checking positions...")
        
        try:
            # Get current account balance
            balance_info = self.hyperliquid_trader.get_account_balance()
            
            if balance_info.get("error"):
                logger.error(f"[ERROR] Failed to check balance: {balance_info.get('error')}")
                return
            
            logger.info(f"[OK] Account Status:")
            logger.info(f"   Total Collateral: ${balance_info.get('total_collateral', 0):.2f}")
            logger.info(f"   Open Positions: {balance_info.get('open_positions', 0)}")
            
            # Get list of open positions
            open_positions = self.hyperliquid_trader.get_open_positions()
            
            if not open_positions:
                logger.info(f"[OK] No open positions")
                return
            
            # Thresholds are stored as fractions (e.g. 0.30); compared against raw price-move
            # percentage, NOT leveraged ROE - otherwise the effective stop distance shrinks as
            # leverage increases (a 30% ROE stop at 15x leverage is only a ~2% price move)
            take_profit_threshold = self.take_profit_pct * 100
            stop_loss_threshold = self.stop_loss_pct * 100

            logger.info(f"[OK] Open positions:")
            for pos in open_positions:
                price_move_pct = ((pos.current_price - pos.entry_price) / pos.entry_price) * 100
                if pos.side.value == "SHORT":
                    price_move_pct = -price_move_pct

                pnl_symbol = "📈" if price_move_pct > 0 else "📉"
                logger.info(f"   {pos.symbol}: {pos.size} units @ ${pos.entry_price:.6f}")
                logger.info(
                    f"      Current: ${pos.current_price:.6f} {pnl_symbol} {price_move_pct:+.2f}% price move "
                    f"(ROE {pos.unrealized_pnl_percentage:+.2f}%)"
                )
                logger.info(f"      P&L: ${pos.unrealized_pnl:+.2f}")
                if pos.funding_paid:
                    funding_label = "paid" if pos.funding_paid > 0 else "received"
                    logger.info(f"      Funding {funding_label} since open: ${abs(pos.funding_paid):.2f}")

                if price_move_pct >= take_profit_threshold:
                    logger.info(f"   [TP HIT] {pos.symbol} price moved +{price_move_pct:.2f}% (threshold {take_profit_threshold:.2f}%)")
                    self._close_position_now(pos, reason="TAKE_PROFIT")
                elif price_move_pct <= stop_loss_threshold:
                    logger.info(f"   [SL HIT] {pos.symbol} price moved {price_move_pct:.2f}% (threshold {stop_loss_threshold:.2f}%)")
                    self._close_position_now(pos, reason="STOP_LOSS")
        
        except Exception as e:
            logger.error(f"[ERROR] Position monitoring failed: {e}", exc_info=True)

    def _close_position_now(self, pos, reason: str):
        """Close a single open position via the exchange and reconcile the matching TradeRecord."""
        signed_size = pos.size if pos.side.value == "LONG" else -pos.size

        close_result = self.hyperliquid_trader.close_position(
            symbol=pos.symbol,
            position_size=signed_size,
            current_price=pos.current_price,
            slippage=self.slippage
        )

        if not close_result.success:
            logger.error(f"[ERROR] Failed to close {pos.symbol} ({reason}): {close_result.error}")
            return

        # Net of funding paid/received over the position's life (see PositionData.funding_paid
        # caveat: sign convention assumed, not yet verified against a live funded account)
        net_pnl = pos.unrealized_pnl - pos.funding_paid
        logger.info(
            f"[SUCCESS] Closed {pos.symbol} ({reason}) @ ${close_result.exit_price:.6f} | "
            f"price P&L ${pos.unrealized_pnl:+.2f}, funding ${-pos.funding_paid:+.2f}, net ${net_pnl:+.2f}"
        )

        # Reconcile against the most recent open trade record for this symbol
        matching_trade = next(
            (t for t in reversed(self.trades_today) if t.symbol == pos.symbol and t.status == "OPEN"),
            None
        )
        if matching_trade:
            matching_trade.status = reason
            matching_trade.exit_price = close_result.exit_price
            matching_trade.pnl = net_pnl
            matching_trade.pnl_percentage = (
                net_pnl / pos.collateral_used if pos.collateral_used else pos.unrealized_pnl_percentage / 100
            )
            self._save_state()
    
    async def run_trading_loop(self):
        """Main autonomous trading loop - runs indefinitely"""
        self.is_running = True
        
        logger.info("\n" + "="*70)
        logger.info("[START] AUTONOMOUS TRADING LOOP STARTED")
        logger.info("="*70)
        logger.info(f"Wallet: {self.wallet_address[:10]}...")
        logger.info(f"Position Size: ${self.position_size_usd}")
        logger.info(f"Max Concurrent: {self.max_concurrent_positions}")
        logger.info(f"Max Daily Trades: {self.max_daily_trades}")
        logger.info(f"Trading Enabled: {self.trading_enabled}")
        logger.info("Press Ctrl+C to stop\n")
        
        # Initialize trader (official SDK - sync method)
        if not self.initialize_trader():
            logger.error("[ERROR] Failed to initialize trader, exiting")
            return
        
        # Check account balance
        logger.info("\n[CHECK] Verifying account balance...")
        balance_info = self.hyperliquid_trader.get_account_balance()
        
        if balance_info.get("error"):
            logger.error(f"[ERROR] Failed to check account balance: {balance_info.get('error')}")
            logger.error("Cannot proceed without balance information")
            return
        
        total_balance = balance_info.get("total_collateral", 0)
        
        # Check total balance
        if total_balance < self.position_size_usd:
            logger.error("[ERROR] Total balance insufficient for trading!")
            logger.error(f"   Need: ${self.position_size_usd:.2f}")
            logger.error(f"   Have: ${total_balance:.2f}")
            return
        
        logger.info("[OK] Account balance verified - ready to trade!")
        logger.info(f"   Total collateral: ${total_balance:,.2f}")
        logger.info(f"   Position size: ${self.position_size_usd:.2f}")
        
        # Reset trades on startup
        self.trades_today = []
        
        # Create monitoring task
        monitoring_task = asyncio.create_task(self._monitoring_loop())
        
        try:
            while self.is_running:
                try:
                    # Execute trading cycle
                    await self.execute_trading_cycle()
                    
                    # Wait for next cycle
                    logger.info(f"\n[WAIT] Waiting {self.execution_interval_minutes} minutes until next cycle...")
                    await asyncio.sleep(self.execution_interval_minutes * 60)
                
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"[ERROR] Trading cycle crashed: {e}", exc_info=True)
                    logger.info("Retrying in 5 minutes...")
                    await asyncio.sleep(300)
        
        finally:
            self.is_running = False
            monitoring_task.cancel()
            logger.info("\n[STOP] Autonomous trading loop stopped")
            self._print_session_summary()
    
    async def _monitoring_loop(self):
        """Background monitoring loop - runs every 5 minutes"""
        while self.is_running:
            try:
                await asyncio.sleep(self.monitoring_interval_seconds)
                if self.is_running:
                    await self.monitor_positions()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[ERROR] Monitoring loop error: {e}", exc_info=True)
    
    def _print_session_summary(self):
        """Print summary of today's trading"""
        logger.info("\n" + "="*70)
        logger.info("[SUMMARY] TRADING SESSION SUMMARY")
        logger.info("="*70)
        logger.info(f"Total Trades Today: {len(self.trades_today)}")
        
        if self.trades_today:
            buy_trades = [t for t in self.trades_today if t.signal == "BUY"]
            sell_trades = [t for t in self.trades_today if t.signal == "SELL"]
            
            logger.info(f"Buy Orders: {len(buy_trades)}")
            logger.info(f"Sell Orders: {len(sell_trades)}")
            
            logger.info(f"\n[TRADES] Executed:")
            for i, trade in enumerate(self.trades_today, 1):
                logger.info(f"  {i}. {trade.symbol} - {trade.signal} @ {trade.leverage:.1f}x")
                logger.info(f"     Entry: ${trade.entry_price:.6f}")
                logger.info(f"     Status: {trade.status}")
                if trade.pnl:
                    logger.info(f"     P&L: ${trade.pnl:.2f} ({trade.pnl_percentage * 100:.1f}%)")
        
        logger.info("="*70 + "\n")


async def main():
    """Main entry point"""
    try:
        trader = AutonomousTrader()
        await trader.run_trading_loop()
    except KeyboardInterrupt:
        logger.info("\n[INTERRUPT] Interrupted by user")
    except Exception as e:
        logger.error(f"[ERROR] Fatal error: {e}", exc_info=True)


if __name__ == "__main__":
    # Force UTF-8 on stdout/stderr so emoji in log messages don't crash the console handler
    # on Windows, where the default console codepage usually can't encode them
    import sys as _sys
    for _stream in (_sys.stdout, _sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            # encoding='utf-8' - without it, FileHandler falls back to the system codepage on
            # Windows (rarely UTF-8), so emoji in log messages raise UnicodeEncodeError and
            # that log line silently never gets written
            logging.FileHandler('trading_loop.log', encoding='utf-8'),
            logging.StreamHandler()
        ]
    )
    
    asyncio.run(main())
