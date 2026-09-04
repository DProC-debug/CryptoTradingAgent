"""
Inspect exact prepare response and determine correct execute format
"""
import asyncio
import os
from dotenv import dotenv_values
import json
import aiohttp

env = dotenv_values('.env')

NANSEN_API_KEY = env['NANSEN_API_KEY']
PORTFOLIO_WALLET_HYPERLIQUID = env['PORTFOLIO_WALLET_HYPERLIQUID']
NANSEN_BASE_URL = "https://api.nansen.ai/api/v1"

async def main():
    async with aiohttp.ClientSession() as session:
        # Get BTC price
        async with session.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
        ) as response:
            price_data = await response.json()
            btc_price = price_data["bitcoin"]["usd"]
        
        # Call prepare
        prepare_payload = {
            "wallet_address": PORTFOLIO_WALLET_HYPERLIQUID,
            "coin": "BTC",
            "is_buy": True,
            "size": 0.001,
            "price": btc_price,
            "order_type": "market",
            "slippage": 0.03,
            "leverage": 20
        }
        
        async with session.post(
            f"{NANSEN_BASE_URL}/perp/order",
            json=prepare_payload,
            headers={"apikey": NANSEN_API_KEY, "Content-Type": "application/json"}
        ) as response:
            prepare_result = await response.json()
        
        action = prepare_result.get("action")
        
        print("=" * 80)
        print("ACTION OBJECT - DETAILED INSPECTION")
        print("=" * 80)
        print(json.dumps(action, indent=2))
        
        print("\n" + "=" * 80)
        print("KEY FIELDS TO CHECK")
        print("=" * 80)
        
        if isinstance(action, dict):
            for key, value in action.items():
                print(f"\n{key}:")
                if isinstance(value, dict):
                    print(f"  Type: dict with {len(value)} keys")
                    for k, v in value.items():
                        print(f"    {k}: {v}")
                elif isinstance(value, list):
                    print(f"  Type: list with {len(value)} items")
                    if value and isinstance(value[0], dict):
                        print(f"  First item keys: {list(value[0].keys())}")
                else:
                    print(f"  Type: {type(value).__name__}")
                    print(f"  Value: {value}")
        
        # Check if wallet_address is anywhere in the action
        print("\n" + "=" * 80)
        print("SEARCHING FOR WALLET REFERENCES")
        print("=" * 80)
        
        def find_wallet_refs(obj, path=""):
            if isinstance(obj, str):
                if "0x" in obj and len(obj) > 30:
                    print(f"  Found address at {path}: {obj}")
            elif isinstance(obj, dict):
                for k, v in obj.items():
                    find_wallet_refs(v, f"{path}.{k}" if path else k)
            elif isinstance(obj, list):
                for i, item in enumerate(obj):
                    find_wallet_refs(item, f"{path}[{i}]")
        
        find_wallet_refs(action)
        
        # Check Nansen docs hint: maybe execute needs wallet_address too?
        print("\n" + "=" * 80)
        print("HYPOTHESIS: Does execute endpoint need wallet_address?")
        print("=" * 80)
        print("Current execute payload would be:")
        print(json.dumps({
            "action": "...",
            "nonce": prepare_result.get("nonce"),
            "signature": "..."
        }, indent=2))
        
        print("\nMaybe it should include wallet_address:")
        print(json.dumps({
            "wallet_address": PORTFOLIO_WALLET_HYPERLIQUID,
            "action": "...",
            "nonce": prepare_result.get("nonce"),
            "signature": "..."
        }, indent=2))

asyncio.run(main())
