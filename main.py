"""CryptoTradingAgents - Main entry point for quick start"""

import logging
import asyncio
from datetime import datetime

from cryptoagents import CryptoTradingGraph
from cryptoagents.default_config import DEFAULT_CONFIG

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    """Main entry point - demonstrates basic usage"""

    logger.info("=" * 60)
    logger.info("CryptoTradingAgents - Multi-Agent Crypto Trading Framework")
    logger.info("=" * 60)

    # Initialize the trading graph
    try:
        ta = CryptoTradingGraph(debug=True, config=DEFAULT_CONFIG)
    except Exception as e:
        logger.error(f"Failed to initialize CryptoTradingGraph: {e}")
        logger.info("\nTroubleshooting:")
        logger.info("1. Make sure you have a .env file with API keys")
        logger.info("   - OPENROUTER_API_KEY (required)")
        logger.info("   - COINGECKO_API_KEY (optional)")
        logger.info("   - NANSEN_API_KEY (optional)")
        logger.info("2. Copy .env.example to .env and fill in your keys")
        return

    # Get market overview
    logger.info("\nFetching market overview...")
    overview = ta.get_market_overview()
    if overview:
        logger.info(f"Market timestamp: {overview.get('timestamp')}")
        logger.info(
            f"BTC Dominance: {overview.get('global', {}).get('btc_market_cap_percentage', 0):.2f}%"
        )

    # Run analysis on Bitcoin
    logger.info("\n" + "=" * 60)
    logger.info("Running analysis on Bitcoin (BTC)...")
    logger.info("=" * 60)

    success, decision = await ta.propagate("BTC", datetime.now().strftime("%Y-%m-%d"))

    if success:
        logger.info("\n✓ Analysis completed!")
        logger.info(f"Crypto: {decision.get('crypto')}")
        logger.info(f"Signal: {decision.get('signal')}")
        logger.info(f"Confidence: {decision.get('confidence'):.2%}")
        logger.info(f"Position Size: {decision.get('position_size', 0):.1%}")
        logger.info(f"Risk/Reward Ratio: {decision.get('risk_reward_ratio', 0):.2f}:1")
        logger.info(f"Max Portfolio Loss: {decision.get('max_portfolio_loss', 0):.2%}")
        logger.info(f"\nTrading Reasoning:\n{decision.get('reasoning')}")

        # Print full analysis
        if decision.get("analysis"):
            logger.info("\n" + "=" * 60)
            logger.info("DETAILED ANALYSIS BREAKDOWN")
            logger.info("=" * 60)
            
            analysis = decision["analysis"]
            
            # Show market data
            if analysis.get("market_data"):
                logger.info(f"\nMarket Data:")
                logger.info(f"  Price: ${analysis['market_data'].get('usd', 0):,.2f}")
                logger.info(f"  Market Cap: ${analysis['market_data'].get('usd_market_cap', 0):,.0f}")
            
            # Show analyst results
            if analysis.get("analyses"):
                logger.info("\n📊 ANALYST RESULTS:")
                for analyst_name, result in analysis["analyses"].items():
                    if result:
                        logger.info(f"\n  {analyst_name.upper()} Analyst:")
                        if hasattr(result, 'score'):
                            logger.info(f"    Score: {result.score:+.2f}")
                            logger.info(f"    Confidence: {result.confidence:.0%}")
                            logger.info(f"    Reasoning: {result.reasoning}")
                        elif isinstance(result, dict):
                            logger.info(f"    {result}")
            
            # Show synthesized signal
            if analysis.get("synthesized_signal"):
                logger.info("\n📈 SYNTHESIZED SIGNAL:")
                signal = analysis["synthesized_signal"]
                logger.info(f"  Signal: {signal.get('signal')}")
                logger.info(f"  Overall Score: {signal.get('overall_score'):+.2f}")
                logger.info(f"  Confidence: {signal.get('confidence'):.0%}")
            
            # Show debate results
            if analysis.get("debate_result"):
                logger.info("\n🎤 RESEARCHER DEBATE:")
                debate = analysis["debate_result"]
                logger.info(f"  Winner: {debate.get('winner').upper()}")
                logger.info(f"  Consensus Score: {debate.get('consensus_score'):+.2f}")
                logger.info(f"  Bullish Arguments: {debate.get('bullish_arguments')}")
                logger.info(f"  Bearish Arguments: {debate.get('bearish_arguments')}")
                logger.info(f"  Reasoning: {debate.get('reasoning')}")
            
            # Show trader decision
            if analysis.get("trade_decision"):
                logger.info("\n💰 TRADER DECISION:")
                trade = analysis["trade_decision"]
                logger.info(f"  Signal: {trade.get('signal')} (Confidence: {trade.get('confidence'):.0%})")
                if trade.get('entry_price'):
                    logger.info(f"  Entry: ${trade.get('entry_price'):,.2f}")
                    logger.info(f"  Stop Loss: ${trade.get('stop_loss'):,.2f}")
                    logger.info(f"  Take Profit: ${trade.get('take_profit'):,.2f}")
                    logger.info(f"  Risk/Reward: {trade.get('risk_reward_ratio'):.2f}:1")
            
            # Show risk metrics
            if analysis.get("risk_metrics"):
                logger.info("\n⚠️  RISK ASSESSMENT:")
                risk = analysis["risk_metrics"]
                logger.info(f"  Adjusted Position: {risk.get('adjusted_position_size', 0):.1%}")
                logger.info(f"  Max Portfolio Loss: {risk.get('max_portfolio_loss', 0):.2%}")
                if risk.get('loss_percentage'):
                    logger.info(f"  Loss at Stop: {risk.get('loss_percentage'):.2f}%")
                if risk.get('gain_percentage'):
                    logger.info(f"  Gain at Target: {risk.get('gain_percentage'):.2f}%")
                logger.info(f"  Reasoning: {risk.get('reasoning')}")
            
            # Show portfolio information
            if analysis.get("portfolio"):
                logger.info("\n💼 PORTFOLIO MANAGEMENT:")
                portfolio = analysis["portfolio"]
                logger.info(f"  Total Value: ${portfolio.get('total_value', 0):,.2f}")
                logger.info(f"  Holdings: {portfolio.get('num_holdings', 0)} assets")
                logger.info(f"  Stablecoin Reserve: {portfolio.get('stablecoin_reserve', 0):.1%}")
                logger.info(f"  Cash Available: ${portfolio.get('cash_available', 0):,.2f}")
                logger.info(f"  Diversification Score: {portfolio.get('diversification_score', 0):.0f}/100")
                logger.info(f"  Largest Position: {portfolio.get('largest_position', 0):.1%}")
                
                if portfolio.get("rebalance_actions"):
                    logger.info("\n  Rebalancing Recommendations:")
                    for action in portfolio["rebalance_actions"]:
                        logger.info(f"    • {action['symbol']}: {action['action']} {abs(action['amount_usd']):,.2f} USD")
                        logger.info(f"      Urgency: {action['urgency']} | {action['reasoning']}")
    else:
        logger.error(f"Analysis failed: {decision.get('error')}")

    logger.info("\n" + "=" * 60)
    logger.info("Next steps:")
    logger.info("1. Review the analysis results above")
    logger.info("2. Run backtests with: python backtest_cli.py --symbol BTC --days 90")
    logger.info("3. Run the autonomous loop with: python cli/autonomous_trader.py")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
