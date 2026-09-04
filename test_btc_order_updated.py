"""
Test BTC $50 order with updated HyperliquidTrader that includes wallet_address in execute
"""
import asyncio
import os
from dotenv import dotenv_values
from cryptoagents.exchanges.hyperliquid_trader import HyperliquidTrader
import sys

# Silence other logging
import logging
logging.basicConfig(level=logging.INFO, format='%(message)s')

env = dotenv_values('.env')

NANSEN_API_KEY = env['NANSEN_API_KEY']
PORTFOLIO_WALLET = env['PORTFOLIO_WALLET_HYPERLIQUID']
PORTFOLIO_PK = env['PORTFOLIO_WALLET_PRIVATE_KEY']

async def main():
    print("=" * 80)
    print("BTC $50 ORDER TEST WITH UPDATED TRADER")
    print("=" * 80)
    
    # Verify env vars
    print(f"\n[CONFIG CHECK]")
    print(f"  API Key: {NANSEN_API_KEY[:10]}...{NANSEN_API_KEY[-5:]}")
    print(f"  Wallet: {PORTFOLIO_WALLET}")
    print(f"  Private Key: {PORTFOLIO_PK[:10]}...{PORTFOLIO_PK[-5:]}")
    
    # Initialize trader
    trader = HyperliquidTrader(
        nansen_api_key=NANSEN_API_KEY,
        wallet_address=PORTFOLIO_WALLET,
        wallet_private_key=PORTFOLIO_PK,
        max_leverage=20
    )
    
    # Check balance
    print(f"\n[BALANCE CHECK]")
    balance = await trader.get_account_balance()
    print(f"  Perpetuals USDC: ${balance.get('usdc_balance', 0):.2f}")
    print(f"  Spot USDC: ${balance.get('spot_usdc_balance', 0):.2f}")
    print(f"  Total USDC: ${balance.get('total_usdc', 0):.2f}")
    
    if balance.get('error'):
        print(f"  ERROR: {balance['error']}")
        return
    
    if balance.get('total_usdc', 0) < 50:
        print(f"  ERROR: Insufficient balance for $50 order")
        return
    
    # Get BTC price
    print(f"\n[MARKET DATA]")
    async with trader.session.get(
        "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
    ) as response:
        price_data = await response.json()
        btc_price = price_data["bitcoin"]["usd"]
    print(f"  BTC Price: ${btc_price:.2f}")
    
    # Execute order
    print(f"\n[OPENING $50 BTC LONG POSITION]")
    result = await trader.open_position(
        symbol="BTC",
        is_buy=True,
        size_usd=50.0,
        leverage=20,
        slippage=0.03,
        price=btc_price,
        order_type="market"
    )
    
    print(f"\n[ORDER RESULT]")
    print(f"  Success: {result.success}")
    print(f"  Symbol: {result.symbol}")
    print(f"  Side: {result.side}")
    print(f"  Entry Price: ${result.entry_price:.2f}" if result.entry_price else "  Entry Price: None")
    print(f"  Size (USD): ${result.size:.2f}" if result.size else "  Size: None")
    print(f"  Leverage: {result.leverage}x" if result.leverage else "  Leverage: None")
    print(f"  Error: {result.error}" if result.error else "  Error: None")
    
    if result.success:
        print(f"\n✅ ORDER EXECUTED SUCCESSFULLY!")
        print(f"   Position ID: {result.position_id}")
    else:
        print(f"\n❌ ORDER FAILED")
    
    await trader.session.close()

# Run the test
try:
    asyncio.run(main())
except KeyboardInterrupt:
    print("\n\nTest interrupted")
    sys.exit(0)
except Exception as e:
    print(f"\n\n❌ Error: {e}")
    import traceback
    traceback.print_exc()
