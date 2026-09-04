#!/usr/bin/env python3
"""
Autonomous Trading Agent - CLI Entry Point
Start your autonomous crypto trading agent with this command:
    python cli/autonomous_trader.py
"""

import sys
import asyncio
import logging
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from cryptoagents.autonomous_trading_loop import AutonomousTrader

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('autonomous_trader.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


def print_banner():
    """Print startup banner"""
    banner = """
===============================================================================
                   AUTONOMOUS CRYPTO TRADING AGENT
===============================================================================
    Multi-Agent Framework with Hyperliquid Perpetuals Integration

    * 5 Parallel AI Analysts (Blockchain, Sentiment, Technical...)
    * Intelligent Altcoin Selection (Top 100 by Market Cap)
    * Autonomous Position Management (TP/SL Auto-Close)
    * Real-Time P&L Tracking and Statistics
    * Full Risk Management and Daily Limits

===============================================================================
"""
    print(banner)


def main():
    """Main entry point"""
    print_banner()
    
    logger.info("[START] Starting Autonomous Trading Agent...")
    logger.info(f"Log file: autonomous_trader.log")
    
    try:
        trader = AutonomousTrader()
        asyncio.run(trader.run_trading_loop())
    except KeyboardInterrupt:
        logger.info("\n[STOP] Trading agent stopped by user")
        print("\n[OK] Agent shutdown complete. Goodbye!\n")
        sys.exit(0)
    except Exception as e:
        logger.error(f"[ERROR] Fatal error: {e}", exc_info=True)
        print(f"\n[ERROR] {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
