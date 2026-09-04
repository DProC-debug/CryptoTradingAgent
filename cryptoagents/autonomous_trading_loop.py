"""
Autonomous Trading Loop
Continuously executes trading cycles without manual intervention
"""

import asyncio
import logging
import os
from datetime import datetime
from typing import Optional, List, Dict
from dotenv import load_dotenv

from cryptoagents.graph.trading_graph import CryptoTradingGraph
from cryptoagents.utilities.coin_selector import CoinSelector
from cryptoagents.dataflows.coingecko_api import CoinGeckoAPI
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
        self.max_daily_trades = int(os.getenv("HYPERLIQUID_MAX_DAILY_TRADES", "10"))
        self.position_size_usd = float(os.getenv("HYPERLIQUID_POSITION_SIZE_USD", "50"))
        self.take_profit_pct = float(os.getenv("HYPERLIQUID_TAKE_PROFIT_PCT", "0.30"))
        self.stop_loss_pct = float(os.getenv("HYPERLIQUID_STOP_LOSS_PCT", "-0.30"))
        self.max_leverage = int(os.getenv("HYPERLIQUID_MAX_LEVERAGE", "20"))
        self.slippage = float(os.getenv("HYPERLIQUID_SLIPPAGE", "0.03"))
        self.order_type = os.getenv("HYPERLIQUID_ORDER_TYPE", "market")
        self.coin_selection_weight = os.getenv("HYPERLIQUID_COIN_SELECTION_WEIGHT", "liquidity")
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
        
        # Initialize APIs
        logger.info("[INIT] Initializing APIs...")
        self.coingecko_api = CoinGeckoAPI()
        self.coin_selector = CoinSelector(self.coingecko_api, exclude_symbols=self.exclude_coins)
        self.trading_graph = CryptoTradingGraph(debug=False)
        self.hyperliquid_trader = None
        
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
    
    async def execute_trading_cycle(self):
        """Execute one complete trading cycle: select, analyze, execute"""
        self.cycle_count += 1
        logger.info(f"\n{'='*70}")
        logger.info(f"[CYCLE] #{self.cycle_count} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"{'='*70}")
        
        try:
            # Step 1: Check daily trade limit
            if len(self.trades_today) >= self.max_daily_trades:
                logger.warning(f"[WARN] Daily trade limit reached ({self.max_daily_trades} trades)")
                return
            
            # Step 2: Check concurrent position limit
            if self.hyperliquid_trader:
                open_positions = len(self.hyperliquid_trader.get_open_positions())
                if open_positions >= self.max_concurrent_positions:
                    logger.warning(f"[WARN] Max concurrent positions reached ({open_positions}/{self.max_concurrent_positions})")
                    return
            
            # Step 3: Select a batch of coins for the cycle
            logger.info("\n[STEP 1] Selecting 5 altcoins for batch analysis...")
            market_data = self.coingecko_api.get_market_data(per_page=250, page=1)
            candidate_coins = await self.coin_selector.select_n_random_coins(
                n=5, market_data=market_data, weights=self.coin_selection_weight
            )
            
            if not candidate_coins:
                logger.error("[ERROR] Failed to select candidate coins")
                return
            
            logger.info(f"[OK] Evaluating {len(candidate_coins)} coins in this batch")
            for coin in candidate_coins:
                logger.info(f"   - {coin.symbol}: ${coin.current_price:.6f} (Vol: ${coin.volume_24h_usd:,.0f})")

            actionable_trades = []
            confidence_threshold = 0.0  # RELAXED: Trade on ANY confidence (was 0.5/50%)

            # Step 4: Analyze each coin in the batch
            for coin in candidate_coins:
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
                    # Execute BUY/SELL signals regardless of confidence
                    logger.info(f"[ACTION] Candidate trade identified: {coin.symbol} {signal} @ {confidence * 100:.1f}%")
                    actionable_trades.append({
                        "coin": coin,
                        "signal": signal,
                        "confidence": confidence,
                        "entry_price": entry_price or coin.current_price
                    })
                else:
                    logger.info(f"[SKIP] {coin.symbol} rejected: signal={signal}, confidence={confidence * 100:.1f}%")

            # Step 5: Make trading decision for the batch
            logger.info(f"\n[STEP 3] Evaluating batch results...")
            if not actionable_trades:
                logger.info(f"[SKIP] No actionable BUY/SELL signals in this 5-coin batch")
                logger.info(f"   Waiting {self.execution_interval_minutes} minutes before next cycle")
                return

            for trade_candidate in actionable_trades:
                coin = trade_candidate["coin"]
                signal = trade_candidate["signal"]
                confidence = trade_candidate["confidence"]
                entry_price = trade_candidate["entry_price"]

                if not self.trading_enabled:
                    logger.info(f"[INFO] HYPERLIQUID_TRADING_ENABLED=false")
                    logger.info(f"   Simulating trade for {coin.symbol}: {signal} @ {confidence * 100:.1f}%")
                    self._log_simulated_trade(coin.symbol, signal, confidence, entry_price)
                    continue

                logger.info(f"\n[STEP 4] Executing {signal} order for {coin.symbol}...")
                leverage = min(confidence * self.max_leverage, self.max_leverage)
                is_buy = signal == "BUY"

                logger.info(f"   Order Direction: {'BUY' if is_buy else 'SELL'}")
                logger.info(f"   Position Size: ${self.position_size_usd}")
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
                    size_usd=self.position_size_usd,
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
    
    def _log_simulated_trade(self, symbol, signal, confidence, entry_price):
        """Log a simulated trade (when trading disabled)"""
        logger.info(f"[DEMO] SIMULATED TRADE:")
        logger.info(f"   Symbol: {symbol}")
        logger.info(f"   Signal: {signal}")
        logger.info(f"   Confidence: {confidence * 100:.1f}%")
        leverage = min(confidence * self.max_leverage, self.max_leverage)
        logger.info(f"   Would execute: {signal} {self.position_size_usd}USD @ {leverage:.1f}x leverage")
        logger.info(f"   Entry Price: ${entry_price:.6f}")
        
        # Still record for statistics
        trade = TradeRecord(symbol, signal, confidence, entry_price, leverage)
        self.trades_today.append(trade)

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
            
            # Thresholds are stored as fractions (e.g. 0.30); PositionData reports pct points (e.g. 30.0)
            take_profit_threshold = self.take_profit_pct * 100
            stop_loss_threshold = self.stop_loss_pct * 100
            
            logger.info(f"[OK] Open positions:")
            for pos in open_positions:
                pnl_pct = pos.unrealized_pnl_percentage
                pnl_symbol = "📈" if pnl_pct > 0 else "📉"
                logger.info(f"   {pos.symbol}: {pos.size} units @ ${pos.entry_price:.6f}")
                logger.info(f"      Current: ${pos.current_price:.6f} {pnl_symbol} {pnl_pct:+.2f}%")
                logger.info(f"      P&L: ${pos.unrealized_pnl:+.2f}")

                if pnl_pct >= take_profit_threshold:
                    logger.info(f"   [TP HIT] {pos.symbol} reached +{pnl_pct:.2f}% (threshold {take_profit_threshold:.2f}%)")
                    self._close_position_now(pos, reason="TAKE_PROFIT")
                elif pnl_pct <= stop_loss_threshold:
                    logger.info(f"   [SL HIT] {pos.symbol} reached {pnl_pct:.2f}% (threshold {stop_loss_threshold:.2f}%)")
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

        logger.info(f"[SUCCESS] Closed {pos.symbol} ({reason}) @ ${close_result.exit_price:.6f}")

        # Reconcile against the most recent open trade record for this symbol
        matching_trade = next(
            (t for t in reversed(self.trades_today) if t.symbol == pos.symbol and t.status == "OPEN"),
            None
        )
        if matching_trade:
            matching_trade.status = reason
            matching_trade.exit_price = close_result.exit_price
            matching_trade.pnl = pos.unrealized_pnl
            matching_trade.pnl_percentage = pos.unrealized_pnl_percentage / 100
    
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
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('trading_loop.log'),
            logging.StreamHandler()
        ]
    )
    
    asyncio.run(main())
