"""Backtest Engine - Test trading strategy on historical data"""

import logging
import asyncio
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
import statistics

logger = logging.getLogger(__name__)


@dataclass
class Trade:
    """Represents a single executed trade"""
    symbol: str
    entry_date: datetime
    entry_price: float
    exit_date: Optional[datetime] = None
    exit_price: Optional[float] = None
    position_size: float = 0.0  # % of portfolio
    signal: str = "HOLD"  # BUY, SELL, HOLD
    confidence: float = 0.0
    pnl: float = 0.0  # Profit/Loss in USD
    pnl_percentage: float = 0.0  # % return
    duration_days: int = 0
    reasoning: str = ""
    
    @property
    def is_open(self) -> bool:
        """Check if trade is still open"""
        return self.exit_date is None
    
    @property
    def is_profitable(self) -> bool:
        """Check if trade is profitable"""
        return self.pnl > 0
    
    @property
    def risk_reward_ratio(self) -> float:
        """Calculate risk/reward ratio for this trade"""
        if self.pnl >= 0:
            return abs(self.pnl) / self.position_size if self.position_size > 0 else 0
        return 0


@dataclass
class PortfolioSnapshot:
    """Snapshot of portfolio state at a point in time"""
    timestamp: datetime
    total_value: float
    cash: float
    holdings: Dict[str, float] = field(default_factory=dict)  # {symbol: value_usd}
    positions: Dict[str, float] = field(default_factory=dict)  # {symbol: amount}
    
    @property
    def equity(self) -> float:
        """Total equity value"""
        return self.total_value


@dataclass
class BacktestResult:
    """Complete backtest results and metrics"""
    symbol: str
    start_date: datetime
    end_date: datetime
    initial_capital: float
    final_value: float
    total_return: float  # In USD
    return_percentage: float  # %
    
    # Trade metrics
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0  # Gross profit / Gross loss
    
    # Risk metrics
    max_drawdown: float = 0.0  # % from peak
    max_drawdown_usd: float = 0.0
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0
    
    # Trade statistics
    avg_win: float = 0.0
    avg_loss: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    avg_trade_duration: int = 0
    
    # Portfolio metrics
    trades: List[Trade] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)  # Daily equity values
    drawdown_curve: List[float] = field(default_factory=list)  # Daily drawdown %
    snapshots: List[PortfolioSnapshot] = field(default_factory=list)
    
    def __post_init__(self):
        """Calculate derived metrics"""
        self._calculate_metrics()
    
    def _calculate_metrics(self):
        """Calculate all performance metrics"""
        if not self.trades:
            return
        
        # Count trades
        self.total_trades = len(self.trades)
        closed_trades = [t for t in self.trades if not t.is_open]
        self.winning_trades = len([t for t in closed_trades if t.is_profitable])
        self.losing_trades = len([t for t in closed_trades if not t.is_profitable and t.pnl != 0])
        
        # Win rate
        if self.total_trades > 0:
            self.win_rate = self.winning_trades / len(closed_trades) if closed_trades else 0
        
        # Profit factor
        gross_profit = sum(t.pnl for t in closed_trades if t.pnl > 0)
        gross_loss = abs(sum(t.pnl for t in closed_trades if t.pnl < 0))
        self.profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf') if gross_profit > 0 else 0
        
        # Win/Loss statistics
        winning = [t.pnl for t in closed_trades if t.is_profitable and t.pnl > 0]
        losing = [t.pnl for t in closed_trades if not t.is_profitable and t.pnl < 0]
        
        self.avg_win = statistics.mean(winning) if winning else 0
        self.avg_loss = statistics.mean(losing) if losing else 0
        self.largest_win = max(winning) if winning else 0
        self.largest_loss = abs(min(losing)) if losing else 0
        
        # Trade duration
        durations = [t.duration_days for t in closed_trades if t.duration_days > 0]
        self.avg_trade_duration = int(statistics.mean(durations)) if durations else 0
        
        # Calculate Sharpe, Sortino, Calmar from equity curve
        if len(self.equity_curve) > 1:
            self._calculate_risk_metrics()
    
    def _calculate_risk_metrics(self):
        """Calculate Sharpe, Sortino, Calmar ratios"""
        if len(self.equity_curve) < 2:
            return
        
        # Daily returns
        daily_returns = []
        for i in range(1, len(self.equity_curve)):
            ret = (self.equity_curve[i] - self.equity_curve[i-1]) / self.equity_curve[i-1]
            daily_returns.append(ret)
        
        if not daily_returns:
            return
        
        # Sharpe Ratio (assuming 252 trading days, 0% risk-free rate)
        mean_return = statistics.mean(daily_returns)
        std_dev = statistics.stdev(daily_returns) if len(daily_returns) > 1 else 0
        if std_dev > 0:
            self.sharpe_ratio = (mean_return * 252) / (std_dev * (252 ** 0.5))
        
        # Sortino Ratio (downside deviation only)
        downside_returns = [r for r in daily_returns if r < 0]
        downside_std = statistics.stdev(downside_returns) if len(downside_returns) > 1 else 0
        if downside_std > 0:
            self.sortino_ratio = (mean_return * 252) / (downside_std * (252 ** 0.5))
        
        # Calmar Ratio (annual return / max drawdown)
        annual_return = (self.final_value - self.initial_capital) / self.initial_capital
        if self.max_drawdown > 0:
            self.calmar_ratio = annual_return / self.max_drawdown


class BacktestEngine:
    """Engine for backtesting trading strategies on historical data"""
    
    def __init__(
        self,
        trading_graph,
        initial_capital: float = 100000.0,
        max_position_size: float = 0.10,  # 10% per position
        slippage: float = 0.001,  # 0.1% slippage
    ):
        """
        Initialize Backtest Engine
        
        Args:
            trading_graph: CryptoTradingGraph instance for analysis
            initial_capital: Starting portfolio value in USD
            max_position_size: Maximum position size as % of portfolio
            slippage: Trading slippage as decimal (0.001 = 0.1%)
        """
        self.trading_graph = trading_graph
        self.initial_capital = initial_capital
        self.max_position_size = max_position_size
        self.slippage = slippage
        
        self.current_portfolio_value = initial_capital
        self.trades: List[Trade] = []
        self.positions: Dict[str, Trade] = {}  # Open positions by symbol
        self.equity_curve: List[float] = [initial_capital]
        self.snapshots: List[PortfolioSnapshot] = []
        
        logger.info("BacktestEngine initialized")
        logger.info(f"  Initial Capital: ${initial_capital:,.2f}")
        logger.info(f"  Max Position Size: {max_position_size:.1%}")
        logger.info(f"  Slippage: {slippage:.2%}")
    
    def run_backtest(
        self,
        symbol: str,
        historical_prices: List[Tuple[datetime, float]],
        analyze_func=None
    ) -> BacktestResult:
        """
        Run backtest on historical price data
        
        Args:
            symbol: Cryptocurrency symbol (e.g., 'BTC')
            historical_prices: List of (datetime, price) tuples, sorted by date
            analyze_func: Optional function to analyze each date, returns (signal, confidence, score)
                         If None, uses trading_graph.analyze()
        
        Returns:
            BacktestResult with complete performance metrics
        """
        logger.info(f"\n{'='*60}")
        logger.info(f"BACKTEST: {symbol}")
        logger.info(f"{'='*60}")
        logger.info(f"Period: {historical_prices[0][0].date()} to {historical_prices[-1][0].date()}")
        logger.info(f"Data points: {len(historical_prices)}")
        
        # Reset state
        self.current_portfolio_value = self.initial_capital
        self.trades = []
        self.positions = {}
        self.equity_curve = [self.initial_capital]
        self.snapshots = []
        
        # Process each historical data point
        for i, (date, price) in enumerate(historical_prices):
            logger.debug(f"Processing {symbol} on {date.date()}: ${price:,.2f}")
            
            # Get trading signal for this date
            try:
                if analyze_func:
                    signal, confidence, score = analyze_func(symbol, date, price)
                else:
                    # Use trading graph's analyzer (async)
                    success, decision = asyncio.run(self.trading_graph.propagate(symbol, date.strftime("%Y-%m-%d")))
                    if success:
                        signal = decision.get("signal", "HOLD")
                        confidence = decision.get("confidence", 0.0)
                        score = decision.get("analysis", {}).get("synthesized_signal", {}).get("overall_score", 0)
                    else:
                        signal, confidence, score = "HOLD", 0.5, 0.0
            except Exception as e:
                logger.debug(f"Analysis failed for {symbol} on {date.date()}: {e}")
                signal, confidence, score = "HOLD", 0.5, 0.0
            
            # Execute trades based on signal
            if symbol in self.positions:
                open_trade = self.positions[symbol]
                
                # Check if we should close position
                if signal == "SELL" or (signal == "HOLD" and confidence < 0.5):
                    pnl = self._close_trade(symbol, price, date)
                    logger.info(f"  CLOSED: {symbol} @ ${price:,.2f} | P&L: {pnl:+.2f}")
            
            else:  # No open position
                # Check if we should open position
                if signal == "BUY" and confidence > 0.6:
                    position_size = min(self.max_position_size, confidence * 0.1)
                    trade = self._open_trade(symbol, price, date, signal, confidence, score, position_size)
                    logger.info(f"  OPENED: {symbol} @ ${price:,.2f} ({position_size:.1%}) | Confidence: {confidence:.0%}")
            
            # Update equity curve with current market values
            self.equity_curve.append(self.current_portfolio_value)
            
            # Create snapshot
            snapshot = PortfolioSnapshot(
                timestamp=date,
                total_value=self.current_portfolio_value,
                cash=self.current_portfolio_value * (1 - sum(self.positions.values()).__sizeof__()),  # Simplified
                holdings={symbol: self.current_portfolio_value * 0.1} if symbol in self.positions else {}
            )
            self.snapshots.append(snapshot)
        
        # Close any remaining open positions at final price
        final_date, final_price = historical_prices[-1]
        for sym in list(self.positions.keys()):
            self._close_trade(sym, final_price, final_date)
        
        # Calculate results
        result = self._calculate_backtest_result(symbol, historical_prices)
        self._print_backtest_summary(result)
        
        return result
    
    def _open_trade(
        self,
        symbol: str,
        price: float,
        date: datetime,
        signal: str,
        confidence: float,
        score: float,
        position_size: float
    ) -> Trade:
        """Open a new trade"""
        # Apply slippage to entry price
        entry_price = price * (1 + self.slippage)
        
        # Calculate position value
        position_value = self.current_portfolio_value * position_size
        amount = position_value / entry_price
        
        trade = Trade(
            symbol=symbol,
            entry_date=date,
            entry_price=entry_price,
            position_size=position_size,
            signal=signal,
            confidence=confidence,
            reasoning=f"Score: {score:+.2f}, Confidence: {confidence:.0%}"
        )
        
        self.trades.append(trade)
        self.positions[symbol] = trade
        
        # Reduce portfolio by position value
        self.current_portfolio_value -= position_value
        
        return trade
    
    def _close_trade(self, symbol: str, price: float, date: datetime) -> float:
        """Close an open trade and calculate P&L"""
        if symbol not in self.positions:
            return 0.0
        
        trade = self.positions.pop(symbol)
        
        # Apply slippage to exit price
        exit_price = price * (1 - self.slippage)
        
        # Calculate P&L
        position_value_at_entry = self.current_portfolio_value + trade.position_size * self.initial_capital
        position_value_at_exit = (position_value_at_entry / trade.entry_price) * exit_price
        
        pnl = position_value_at_exit - position_value_at_entry
        pnl_percentage = (exit_price - trade.entry_price) / trade.entry_price
        
        # Update trade
        trade.exit_date = date
        trade.exit_price = exit_price
        trade.pnl = pnl
        trade.pnl_percentage = pnl_percentage
        trade.duration_days = (date - trade.entry_date).days
        
        # Update portfolio
        self.current_portfolio_value += position_value_at_exit
        
        return pnl
    
    def _calculate_backtest_result(
        self,
        symbol: str,
        historical_prices: List[Tuple[datetime, float]]
    ) -> BacktestResult:
        """Calculate comprehensive backtest results"""
        
        start_date = historical_prices[0][0]
        end_date = historical_prices[-1][0]
        final_value = self.current_portfolio_value
        total_return = final_value - self.initial_capital
        return_percentage = (final_value - self.initial_capital) / self.initial_capital
        
        # Calculate drawdown
        peak = self.initial_capital
        max_dd = 0
        max_dd_usd = 0
        drawdown_curve = []
        
        for value in self.equity_curve:
            if value > peak:
                peak = value
            dd = (peak - value) / peak
            drawdown_curve.append(dd)
            if dd > max_dd:
                max_dd = dd
                max_dd_usd = peak - value
        
        result = BacktestResult(
            symbol=symbol,
            start_date=start_date,
            end_date=end_date,
            initial_capital=self.initial_capital,
            final_value=final_value,
            total_return=total_return,
            return_percentage=return_percentage,
            max_drawdown=max_dd,
            max_drawdown_usd=max_dd_usd,
            trades=self.trades,
            equity_curve=self.equity_curve,
            drawdown_curve=drawdown_curve,
            snapshots=self.snapshots,
        )
        
        return result
    
    def _print_backtest_summary(self, result: BacktestResult):
        """Print formatted backtest results"""
        logger.info("\n" + "="*60)
        logger.info("BACKTEST RESULTS")
        logger.info("="*60)
        
        logger.info(f"\nPERFORMANCE:")
        logger.info(f"  Initial Capital: ${result.initial_capital:,.2f}")
        logger.info(f"  Final Value: ${result.final_value:,.2f}")
        logger.info(f"  Total Return: ${result.total_return:+,.2f} ({result.return_percentage:+.2%})")
        
        logger.info(f"\nTRADES:")
        logger.info(f"  Total: {result.total_trades}")
        logger.info(f"  Winning: {result.winning_trades} ({result.win_rate:.1%})")
        logger.info(f"  Losing: {result.losing_trades}")
        logger.info(f"  Profit Factor: {result.profit_factor:.2f}")
        
        if result.winning_trades > 0:
            logger.info(f"  Avg Win: ${result.avg_win:+,.2f}")
            logger.info(f"  Largest Win: ${result.largest_win:+,.2f}")
        if result.losing_trades > 0:
            logger.info(f"  Avg Loss: ${result.avg_loss:+,.2f}")
            logger.info(f"  Largest Loss: ${result.largest_loss:+,.2f}")
        
        logger.info(f"  Avg Trade Duration: {result.avg_trade_duration} days")
        
        logger.info(f"\nRISK METRICS:")
        logger.info(f"  Max Drawdown: {result.max_drawdown:.2%} (${result.max_drawdown_usd:,.2f})")
        logger.info(f"  Sharpe Ratio: {result.sharpe_ratio:.2f}")
        logger.info(f"  Sortino Ratio: {result.sortino_ratio:.2f}")
        logger.info(f"  Calmar Ratio: {result.calmar_ratio:.2f}")
        
        logger.info("\n" + "="*60)
