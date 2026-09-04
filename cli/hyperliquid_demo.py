#!/usr/bin/env python
"""
Hyperliquid Integration Demo and Test
Demonstrates order placement, position management, and monitoring
"""

import sys
import logging
import asyncio
from pathlib import Path
from dotenv import load_dotenv
import os

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from cryptoagents.exchanges import HyperliquidTrader
from cryptoagents.utilities.coin_selector import CoinSelector
from cryptoagents.dataflows.coingecko_api import CoinGeckoAPI
from cryptoagents.graph.trading_graph import CryptoTradingGraph

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()


async def demo_hyperliquid_trading():
    """
    Demo: Hyperliquid trading flow
    Shows: Selection → Analysis → Order Placement → Monitoring → Closing
    """
    logger.info("=" * 70)
    logger.info("HYPERLIQUID TRADING INTEGRATION DEMO")
    logger.info("=" * 70)
    
    # Get configuration
    nansen_api_key = os.getenv("NANSEN_API_KEY")
    wallet_address = os.getenv("PORTFOLIO_WALLET_HYPERLIQUID")
    wallet_private_key = os.getenv("PORTFOLIO_WALLET_PRIVATE_KEY")
    max_leverage = int(os.getenv("HYPERLIQUID_MAX_LEVERAGE", "20"))
    position_size_usd = float(os.getenv("HYPERLIQUID_POSITION_SIZE_USD", "1000"))
    take_profit_pct = float(os.getenv("HYPERLIQUID_TAKE_PROFIT_PCT", "0.30"))
    stop_loss_pct = float(os.getenv("HYPERLIQUID_STOP_LOSS_PCT", "-0.30"))
    slippage = float(os.getenv("HYPERLIQUID_SLIPPAGE", "0.03"))
    
    if not nansen_api_key or not wallet_address:
        logger.error("Missing NANSEN_API_KEY or PORTFOLIO_WALLET_HYPERLIQUID in .env")
        return
    
    logger.info("\n📋 Configuration:")
    logger.info(f"  Wallet: {wallet_address[:10]}...")
    logger.info(f"  Max Leverage: {max_leverage}x")
    logger.info(f"  Position Size: ${position_size_usd:,.0f}")
    logger.info(f"  Take Profit: {take_profit_pct*100:.1f}%")
    logger.info(f"  Stop Loss: {stop_loss_pct*100:.1f}%")
    logger.info(f"  Slippage: {slippage*100:.1f}%")
    
    # Initialize APIs and trader
    logger.info("\n🔌 Initializing APIs...")
    
    coingecko_api = CoinGeckoAPI()
    trading_graph = CryptoTradingGraph(debug=False)
    
    async with HyperliquidTrader(nansen_api_key, wallet_address, wallet_private_key, max_leverage) as trader:
        
        # Step 1: Select random altcoin
        logger.info("\n" + "=" * 70)
        logger.info("STEP 1: SELECT RANDOM ALTCOIN")
        logger.info("=" * 70)
        
        coin_selector = CoinSelector(coingecko_api)
        
        # Fetch market data
        logger.info("Fetching market data...")
        market_data = coingecko_api.get_market_data(per_page=250, page=1)
        
        # Select random coin
        selected_coin = await coin_selector.select_random_coin(market_data)
        if not selected_coin:
            logger.error("No tradeable coins available")
            return
        
        symbol = selected_coin.symbol
        current_price = selected_coin.current_price
        
        # Step 2: Analyze the selected coin
        logger.info("\n" + "=" * 70)
        logger.info("STEP 2: ANALYZE SELECTED COIN")
        logger.info("=" * 70)
        
        logger.info(f"Running analysis on {symbol}...")
        success, analysis_result = await trading_graph.propagate(symbol, None)
        
        if not success:
            logger.error(f"Analysis failed for {symbol}")
            return
        
        signal = analysis_result.get("signal", "HOLD")
        confidence = analysis_result.get("confidence", 0)
        trader_decision = analysis_result.get("trader_decision", {})
        
        logger.info(f"\n📊 Analysis Results:")
        logger.info(f"  Signal: {signal}")
        logger.info(f"  Confidence: {confidence*100:.1f}%")
        logger.info(f"  Entry Price: ${current_price:.2f}")
        
        # Step 3: Determine if we should trade
        logger.info("\n" + "=" * 70)
        logger.info("STEP 3: TRADING DECISION")
        logger.info("=" * 70)
        
        should_trade = signal in ["BUY", "SELL"] and confidence > 0.5
        
        if not should_trade:
            logger.warning(f"Trade signal not strong enough (Signal: {signal}, Confidence: {confidence*100:.1f}%)")
            logger.info("Skipping order placement for this demo.")
            return
        
        # Determine leverage based on confidence
        leverage = int(min(confidence * max_leverage, max_leverage))
        is_buy = signal == "BUY"
        
        logger.info(f"\n✓ Trade approved:")
        logger.info(f"  Direction: {'LONG (BUY)' if is_buy else 'SHORT (SELL)'}")
        logger.info(f"  Symbol: {symbol}")
        logger.info(f"  Leverage: {leverage}x")
        logger.info(f"  Position Size: ${position_size_usd:,.0f}")
        logger.info(f"  Collateral: ${position_size_usd/leverage:,.0f}")
        
        # Step 4: Place order (in demo mode - would be real with live trading)
        logger.info("\n" + "=" * 70)
        logger.info("STEP 4: PLACE ORDER (DEMO MODE)")
        logger.info("=" * 70)
        
        logger.info(f"ℹ️  DEMO MODE: Not placing real order")
        logger.info(f"In production, this would execute:")
        logger.info(f"  POST {trader.nansen_base_url}/perp/order")
        logger.info(f"  Payload:")
        
        payload = {
            "wallet_address": wallet_address,
            "coin": symbol,
            "is_buy": is_buy,
            "size": position_size_usd,
            "order_type": "market",
            "slippage": slippage,
            "leverage": leverage
        }
        
        import json
        logger.info(f"  {json.dumps(payload, indent=4)}")
        
        # Simulate successful order
        logger.info(f"\n✓ Order would be placed successfully (SIMULATED)")
        
        # Step 5: Position monitoring
        logger.info("\n" + "=" * 70)
        logger.info("STEP 5: POSITION MONITORING (SIMULATED)")
        logger.info("=" * 70)
        
        logger.info(f"Monitoring position for take-profit/stop-loss conditions:")
        logger.info(f"  Take Profit: +{take_profit_pct*100:.0f}%")
        logger.info(f"  Stop Loss: {stop_loss_pct*100:.0f}%")
        
        # Simulate price movements
        logger.info(f"\nSimulating price movements...")
        
        price_scenarios = [
            (current_price * 0.95, "-5%", "LOSS"),
            (current_price * 1.10, "+10%", "PROFIT"),
            (current_price * 1.35, "+35%", "TAKE_PROFIT"),
            (current_price * 0.65, "-35%", "STOP_LOSS"),
        ]
        
        for scenario_price, change_pct, scenario_type in price_scenarios:
            logger.info(f"\n  Price movement: {change_pct} → ${scenario_price:.2f}")
            
            if scenario_type == "TAKE_PROFIT":
                logger.info(f"    ✓ TAKE PROFIT TRIGGERED (+{take_profit_pct*100:.0f}%)")
                logger.info(f"    Would close position at ${scenario_price:.2f}")
                pnl = position_size_usd * (take_profit_pct)
                logger.info(f"    Realized P&L: +${pnl:.2f}")
                break
            elif scenario_type == "STOP_LOSS":
                logger.info(f"    ✗ STOP LOSS TRIGGERED ({stop_loss_pct*100:.0f}%)")
                logger.info(f"    Would close position at ${scenario_price:.2f}")
                pnl = position_size_usd * stop_loss_pct
                logger.info(f"    Realized P&L: -${abs(pnl):.2f}")
                break
            else:
                pnl_pct = (scenario_price - current_price) / current_price
                pnl = position_size_usd * pnl_pct / leverage
                logger.info(f"    Unrealized P&L: ${pnl:.2f} ({pnl_pct*100:.1f}%)")
        
        # Portfolio state
        logger.info("\n" + "=" * 70)
        logger.info("PORTFOLIO STATE (IF POSITION WERE OPEN)")
        logger.info("=" * 70)
        
        logger.info(f"Open Positions: 1")
        logger.info(f"Total Collateral Used: ${position_size_usd/leverage:,.0f}")
        logger.info(f"Available for Additional Trades: ~$99,500")
        
        # Trade Statistics
        logger.info("\n" + "=" * 70)
        logger.info("TRADE STATISTICS")
        logger.info("=" * 70)
        
        stats = trader.get_trade_statistics()
        logger.info(f"Total Closed Trades: {stats['total_trades']}")
        logger.info(f"Winning Trades: {stats['winning_trades']}")
        logger.info(f"Losing Trades: {stats['losing_trades']}")
        logger.info(f"Win Rate: {stats['win_rate']*100:.1f}%")
        logger.info(f"Total P&L: ${stats['total_pnl']:.2f}")
        logger.info(f"Profit Factor: {stats['profit_factor']:.2f}")


async def demo_coin_selection():
    """Demo coin selection capabilities"""
    logger.info("\n" + "=" * 70)
    logger.info("COIN SELECTION DEMO")
    logger.info("=" * 70)
    
    coingecko_api = CoinGeckoAPI()
    coin_selector = CoinSelector(coingecko_api)
    
    logger.info("\nFetching market data...")
    market_data = coingecko_api.get_market_data(per_page=250, page=1)
    
    logger.info("\nFetching tradeable candidates...")
    candidates = await coin_selector.fetch_candidates(market_data)
    
    logger.info(f"\nFound {len(candidates)} tradeable coins")
    
    logger.info("\nTop 5 by liquidity:")
    for i, coin in enumerate(coin_selector.get_top_candidates(5), 1):
        logger.info(f"  {i}. {coin.symbol} - Liquidity: {coin.liquidity_score:.1f}/100")
    
    logger.info("\nSelecting 3 random coins:")
    selected = await coin_selector.select_n_random_coins(3, market_data)
    for coin in selected:
        logger.info(f"  - {coin.symbol}")
    
    logger.info("\nCandidate pool statistics:")
    stats = coin_selector.get_statistics()
    logger.info(f"  Total Candidates: {stats['total_candidates']}")
    logger.info(f"  Avg Liquidity Score: {stats['avg_liquidity']:.1f}")
    logger.info(f"  Avg 24h Volume: ${stats['avg_volume']:,.0f}")
    logger.info(f"  Total 24h Volume: ${stats['total_24h_volume']:,.0f}")


async def main():
    """Main entry point"""
    try:
        # Run demos
        await demo_coin_selection()
        await demo_hyperliquid_trading()
        
        logger.info("\n" + "=" * 70)
        logger.info("DEMO COMPLETED")
        logger.info("=" * 70)
        logger.info("\nNext steps:")
        logger.info("1. Review the order placement logic")
        logger.info("2. Update HYPERLIQUID_TRADING_ENABLED=true to enable live trading")
        logger.info("3. Start with small position sizes ($100-500)")
        logger.info("4. Monitor the autonomous trading loop")
        
    except Exception as e:
        logger.error(f"Demo failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
