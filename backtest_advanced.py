#!/usr/bin/env python
"""Advanced Backtest CLI - Run strategy backtests with detailed reporting"""

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


def generate_backtest_html_report(result, filename="backtest_report.html"):
    """Generate HTML report of backtest results"""
    
    # Determine color coding
    return_color = "#28a745" if result.return_percentage >= 0 else "#dc3545"
    pnl_color = "#28a745" if result.total_return >= 0 else "#dc3545"
    wr_color = "#28a745" if result.win_rate >= 0.5 else "#dc3545"
    sharpe_color = "#28a745" if result.sharpe_ratio > 0 else "#dc3545"
    sortino_color = "#28a745" if result.sortino_ratio > 0 else "#dc3545"
    calmar_color = "#28a745" if result.calmar_ratio > 0 else "#dc3545"
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Backtest Report - {result.symbol}</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
            .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
            h1 {{ color: #333; border-bottom: 3px solid #007bff; padding-bottom: 10px; }}
            h2 {{ color: #555; margin-top: 30px; }}
            .metrics {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin: 20px 0; }}
            .metric-card {{ background: #f9f9f9; padding: 15px; border-radius: 5px; border-left: 4px solid #007bff; }}
            .metric-value {{ font-size: 24px; font-weight: bold; color: #007bff; }}
            .metric-label {{ font-size: 12px; color: #666; text-transform: uppercase; }}
            .positive {{ color: #28a745; }}
            .negative {{ color: #dc3545; }}
            table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
            th {{ background: #007bff; color: white; padding: 10px; text-align: left; }}
            td {{ padding: 10px; border-bottom: 1px solid #ddd; }}
            tr:hover {{ background: #f5f5f5; }}
            .chart {{ margin: 20px 0; padding: 20px; background: #f9f9f9; border-radius: 5px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🎯 Backtest Report: {result.symbol}</h1>
            
            <div style="color: #666; margin-bottom: 20px;">
                <p><strong>Period:</strong> {result.start_date.date()} to {result.end_date.date()}</p>
                <p><strong>Generated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}</p>
            </div>
            
            <h2>📊 Performance Summary</h2>
            <div class="metrics">
                <div class="metric-card">
                    <div class="metric-label">Initial Capital</div>
                    <div class="metric-value">${result.initial_capital:,.0f}</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">Final Value</div>
                    <div class="metric-value" style="color: {return_color};">${result.final_value:,.0f}</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">Total Return</div>
                    <div class="metric-value" style="color: {return_color};">{result.return_percentage:+.2%}</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">Profit/Loss</div>
                    <div class="metric-value" style="color: {pnl_color};">${result.total_return:+,.0f}</div>
                </div>
            </div>
            
            <h2>📈 Trade Statistics</h2>
            <div class="metrics">
                <div class="metric-card">
                    <div class="metric-label">Total Trades</div>
                    <div class="metric-value">{result.total_trades}</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">Win Rate</div>
                    <div class="metric-value" style="color: {wr_color};">{result.win_rate:.1%}</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">Profit Factor</div>
                    <div class="metric-value">{result.profit_factor:.2f}</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">Avg Trade Duration</div>
                    <div class="metric-value">{result.avg_trade_duration}d</div>
                </div>
            </div>
            
            <h2>⚠️ Risk Metrics</h2>
            <div class="metrics">
                <div class="metric-card">
                    <div class="metric-label">Max Drawdown</div>
                    <div class="metric-value" style="color: #dc3545;">{result.max_drawdown:.2%}</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">Sharpe Ratio</div>
                    <div class="metric-value" style="color: {sharpe_color};">{result.sharpe_ratio:.2f}</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">Sortino Ratio</div>
                    <div class="metric-value" style="color: {sortino_color};">{result.sortino_ratio:.2f}</div>
                </div>
                <div class="metric-card">
                    <div class="metric-label">Calmar Ratio</div>
                    <div class="metric-value" style="color: {calmar_color};">{result.calmar_ratio:.2f}</div>
                </div>
            </div>
            
            <h2>💰 Trade Analysis</h2>
            {'<p>No trades executed during backtest period.</p>' if not result.trades else _generate_trades_table(result)}
            
            <h2>📉 Equity Curve</h2>
            <div class="chart">
                <p style="color: #666;">Equity curve visualization would be displayed here.</p>
                <p style="color: #666;">Peak Equity: ${max(result.equity_curve):,.0f}</p>
                <p style="color: #666;">Lowest Equity: ${min(result.equity_curve):,.0f}</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html_content)
    
    return filename


def _generate_trades_table(result):
    """Generate HTML table of trades"""
    trades = [t for t in result.trades if not t.is_open]
    if not trades:
        return "<p>No closed trades found.</p>"
    
    rows = ""
    for trade in sorted(trades, key=lambda t: t.entry_date):
        rows += f"""
        <tr>
            <td>{trade.symbol}</td>
            <td>{trade.entry_date.date()}</td>
            <td>${trade.entry_price:,.2f}</td>
            <td>${trade.exit_price:,.2f}</td>
            <td class="{'positive' if trade.pnl_percentage >= 0 else 'negative'}">{trade.pnl_percentage:+.2%}</td>
            <td>${trade.pnl:+,.0f}</td>
            <td>{trade.duration_days}d</td>
        </tr>
        """
    
    return f"""
    <table>
        <thead>
            <tr>
                <th>Symbol</th>
                <th>Entry Date</th>
                <th>Entry Price</th>
                <th>Exit Price</th>
                <th>Return %</th>
                <th>P&L</th>
                <th>Duration</th>
            </tr>
        </thead>
        <tbody>
            {rows}
        </tbody>
    </table>
    """


def run_advanced_backtest(
    symbol: str = "BTC",
    days: int = 90,
    initial_capital: float = 100000.0,
):
    """Run advanced backtest with detailed analysis"""
    
    logger.info("="*70)
    logger.info("CRYPTO TRADING AGENTS - ADVANCED BACKTEST")
    logger.info("="*70)
    
    try:
        # Initialize trading graph
        logger.info(f"\nInitializing trading graph...")
        trading_graph = CryptoTradingGraph(debug=False)
        logger.info("✓ Trading graph initialized")
        
        # Fetch historical data
        logger.info(f"\nFetching historical data for {symbol}...")
        fetcher = HistoricalDataFetcher(trading_graph.coingecko)
        historical_prices = fetcher.fetch_daily_prices(symbol, days=days)
        
        if not historical_prices:
            logger.error(f"Failed to fetch historical data for {symbol}")
            return 1
        
        # Initialize backtest engine
        logger.info(f"\nInitializing backtest engine...")
        engine = BacktestEngine(
            trading_graph=trading_graph,
            initial_capital=initial_capital,
            max_position_size=0.10,
            slippage=0.001,
        )
        logger.info("✓ Backtest engine initialized")
        
        # Advanced analysis function
        def advanced_analyze(symbol, date, price):
            """Advanced analysis using multiple indicators"""
            
            # Find current index
            current_idx = None
            for i, (d, p) in enumerate(historical_prices):
                if d.date() == date.date():
                    current_idx = i
                    break
            
            if current_idx is None or current_idx < 5:
                return "HOLD", 0.5, 0.0
            
            # Calculate multiple indicators
            recent_prices = [p[1] for p in historical_prices[max(0, current_idx-20):current_idx+1]]
            
            # SMA (20-day moving average)
            sma_20 = sum(recent_prices) / len(recent_prices)
            
            # RSI-like calculation
            changes = [recent_prices[i] - recent_prices[i-1] for i in range(1, len(recent_prices))]
            up_avg = sum([c for c in changes if c > 0]) / max(len([c for c in changes if c > 0]), 1)
            down_avg = sum([abs(c) for c in changes if c < 0]) / max(len([c for c in changes if c < 0]), 1)
            rs = up_avg / down_avg if down_avg != 0 else 1
            rsi = 100 - (100 / (1 + rs))
            
            # Momentum (10-day)
            momentum = (recent_prices[-1] - recent_prices[max(0, -10)]) / recent_prices[max(0, -10)]
            
            # Decision logic
            signals = []
            confidence_factors = []
            
            # Price above SMA = bullish
            if price > sma_20:
                signals.append(0.3)
                confidence_factors.append(0.7)
            else:
                signals.append(-0.3)
                confidence_factors.append(0.7)
            
            # RSI signals
            if rsi < 30:
                signals.append(0.5)  # Oversold
                confidence_factors.append(0.8)
            elif rsi > 70:
                signals.append(-0.5)  # Overbought
                confidence_factors.append(0.8)
            else:
                signals.append(0.1)
                confidence_factors.append(0.5)
            
            # Momentum signals
            if momentum > 0.05:
                signals.append(0.4)
                confidence_factors.append(0.8)
            elif momentum < -0.05:
                signals.append(-0.4)
                confidence_factors.append(0.8)
            else:
                signals.append(0.0)
                confidence_factors.append(0.5)
            
            # Combine signals
            overall_score = sum(signals) / len(signals) if signals else 0
            confidence = sum(confidence_factors) / len(confidence_factors)
            
            # Determine action
            if overall_score > 0.2 and confidence > 0.6:
                return "BUY", confidence, overall_score
            elif overall_score < -0.2 and confidence > 0.6:
                return "SELL", confidence, overall_score
            else:
                return "HOLD", 0.5, overall_score
        
        # Run backtest
        logger.info(f"\nRunning advanced backtest for {symbol}...")
        logger.info(f"Data points: {len(historical_prices)}")
        logger.info(f"Period: {historical_prices[0][0].date()} to {historical_prices[-1][0].date()}")
        
        result = engine.run_backtest(
            symbol=symbol,
            historical_prices=historical_prices,
            analyze_func=advanced_analyze
        )
        
        # Generate HTML report
        logger.info(f"\nGenerating HTML report...")
        report_file = Path(__file__).parent.parent.parent / "backtest_report.html"
        generate_backtest_html_report(result, str(report_file))
        logger.info(f"✓ Report saved to: {report_file}")
        
        logger.info("\n" + "="*70)
        logger.info("ADVANCED BACKTEST COMPLETED")
        logger.info("="*70)
        
        return 0
    
    except Exception as e:
        logger.error(f"Backtest failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Run advanced backtest with detailed analysis"
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
    
    exit_code = run_advanced_backtest(
        symbol=args.symbol,
        days=args.days,
        initial_capital=args.capital
    )
    
    sys.exit(exit_code)
