#!/usr/bin/env python
"""Backtest CLI - Run strategy backtests on historical data"""

import sys
import logging
from datetime import datetime
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from cryptoagents.graph.trading_graph import CryptoTradingGraph
from cryptoagents.backtesting import BacktestEngine
from cryptoagents.backtesting.historical_data import HistoricalDataFetcher

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


def run_backtest(
    symbol: str = "BTC",
    days: int = 90,
    initial_capital: float = 100000.0,
):
    """
    Run a backtest on historical data
    
    Args:
        symbol: Cryptocurrency symbol (BTC, ETH, SOL, etc.)
        days: Number of historical days to test
        initial_capital: Starting portfolio value
    """
    
    logger.info("="*70)
    logger.info("CRYPTO TRADING AGENTS - BACKTEST ENGINE")
    logger.info("="*70)
    
    try:
        # Initialize trading graph
        logger.info(f"\nInitializing trading graph...")
        trading_graph = CryptoTradingGraph(debug=False)
        logger.info("✓ Trading graph initialized")
        
        # Initialize historical data fetcher
        logger.info(f"\nFetching historical data for {symbol}...")
        fetcher = HistoricalDataFetcher(trading_graph.coingecko)
        historical_prices = fetcher.fetch_daily_prices(symbol, days=days)
        
        if not historical_prices:
            logger.error(f"Failed to fetch historical data for {symbol}")
            return
        
        # Initialize backtest engine
        logger.info(f"\nInitializing backtest engine...")
        engine = BacktestEngine(
            trading_graph=trading_graph,
            initial_capital=initial_capital,
            max_position_size=0.10,  # 10% per position
            slippage=0.001,  # 0.1% slippage
        )
        logger.info("✓ Backtest engine initialized")
        
        # Run backtest
        logger.info(f"\nRunning backtest for {symbol}...")
        logger.info(f"Data points: {len(historical_prices)}")
        logger.info(f"Period: {historical_prices[0][0].date()} to {historical_prices[-1][0].date()}")
        
        # Simple analysis function for backtest
        def analyze_price(symbol, date, price):
            """Simple analysis based on price momentum"""
            if len(historical_prices) < 20:
                return "HOLD", 0.5, 0.0
            
            current_idx = None
            for i, (d, p) in enumerate(historical_prices):
                if d.date() == date.date():
                    current_idx = i
                    break
            
            if current_idx is None or current_idx < 20:
                return "HOLD", 0.5, 0.0
            
            # Calculate 20-day momentum
            prev_price = historical_prices[current_idx - 20][1]
            momentum = (price - prev_price) / prev_price
            
            if momentum > 0.05:  # 5% gain in 20 days = bullish
                return "BUY", min(0.9, momentum * 10), momentum
            elif momentum < -0.05:  # 5% loss = bearish
                return "SELL", min(0.9, abs(momentum) * 10), momentum
            else:
                return "HOLD", 0.5, momentum
        
        result = engine.run_backtest(
            symbol=symbol,
            historical_prices=historical_prices,
            analyze_func=analyze_price
        )
        
        # Print summary
        logger.info("\n" + "="*70)
        logger.info("BACKTEST COMPLETED SUCCESSFULLY")
        logger.info("="*70)
        
        # Detailed trade analysis
        if result.trades:
            logger.info(f"\nTOPPING TRADES:")
            
            # Sort by P&L
            sorted_trades = sorted(result.trades, key=lambda t: t.pnl, reverse=True)
            
            logger.info(f"\nBest 5 Trades:")
            for i, trade in enumerate(sorted_trades[:5], 1):
                if trade.is_open:
                    logger.info(f"  {i}. OPEN: {trade.symbol} @ ${trade.entry_price:,.2f} ({trade.position_size:.1%})")
                else:
                    logger.info(f"  {i}. {trade.symbol}: ${trade.pnl:+,.2f} ({trade.pnl_percentage:+.2%}) | "
                              f"{trade.duration_days}d")
            
            if len(sorted_trades) > 5:
                logger.info(f"\nWorst 5 Trades:")
                for i, trade in enumerate(sorted_trades[-5:], 1):
                    if not trade.is_open:
                        logger.info(f"  {i}. {trade.symbol}: ${trade.pnl:+,.2f} ({trade.pnl_percentage:+.2%}) | "
                                  f"{trade.duration_days}d")
        
        # Save results to file
        results_file = Path(__file__).parent.parent.parent / "backtest_results.txt"
        with open(results_file, "w") as f:
            f.write(f"Backtest Results for {symbol}\n")
            f.write(f"Date: {datetime.now().isoformat()}\n")
            f.write(f"Period: {result.start_date.date()} to {result.end_date.date()}\n")
            f.write(f"\nPerformance:\n")
            f.write(f"  Initial Capital: ${result.initial_capital:,.2f}\n")
            f.write(f"  Final Value: ${result.final_value:,.2f}\n")
            f.write(f"  Total Return: ${result.total_return:+,.2f} ({result.return_percentage:+.2%})\n")
            f.write(f"\nTrades: {result.total_trades}\n")
            f.write(f"  Winning: {result.winning_trades} ({result.win_rate:.1%})\n")
            f.write(f"  Losing: {result.losing_trades}\n")
            f.write(f"  Profit Factor: {result.profit_factor:.2f}\n")
            f.write(f"\nRisk Metrics:\n")
            f.write(f"  Max Drawdown: {result.max_drawdown:.2%}\n")
            f.write(f"  Sharpe Ratio: {result.sharpe_ratio:.2f}\n")
            f.write(f"  Sortino Ratio: {result.sortino_ratio:.2f}\n")
        
        logger.info(f"\nResults saved to: {results_file}")
        
    except Exception as e:
        logger.error(f"Backtest failed: {e}", exc_info=True)
        return 1
    
    return 0


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Run backtest on historical cryptocurrency data"
    )
    parser.add_argument(
        "--symbol",
        default="BTC",
        help="Cryptocurrency symbol (default: BTC)"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=90,
        help="Number of historical days to backtest (default: 90)"
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=100000.0,
        help="Initial capital in USD (default: 100000)"
    )
    
    args = parser.parse_args()
    
    exit_code = run_backtest(
        symbol=args.symbol,
        days=args.days,
        initial_capital=args.capital
    )
    
    sys.exit(exit_code)
