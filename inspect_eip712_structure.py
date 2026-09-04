"""
Inspect the exact EIP712 structure Nansen returns to understand the signing format
"""
import asyncio
import json
import aiohttp
from dotenv import dotenv_values

env = dotenv_values('.env')

NANSEN_API_KEY = env['NANSEN_API_KEY']
PORTFOLIO_WALLET = env['PORTFOLIO_WALLET_HYPERLIQUID']
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
            "wallet_address": PORTFOLIO_WALLET,
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
        
        eip712 = prepare_result.get("eip712")
        
        print("=" * 80)
        print("COMPLETE EIP712 STRUCTURE FROM PREPARE")
        print("=" * 80)
        print(json.dumps(eip712, indent=2))
        
        print("\n" + "=" * 80)
        print("ANALYSIS")
        print("=" * 80)
        
        # Check for missing EIP712Domain
        types = eip712.get("types", {})
        print(f"\nTypes defined: {list(types.keys())}")
        print(f"EIP712Domain present: {'EIP712Domain' in types}")
        
        # The primaryType
        primary_type = eip712.get("primaryType")
        print(f"Primary Type: {primary_type}")
        print(f"Primary Type fields:")
        if primary_type in types:
            for field in types[primary_type]:
                print(f"  - {field['name']}: {field['type']}")
        
        # Domain values
        domain = eip712.get("domain", {})
        print(f"\nDomain values:")
        for k, v in domain.items():
            print(f"  {k}: {v}")
        
        # Message values
        message = eip712.get("message", {})
        print(f"\nMessage values:")
        for k, v in message.items():
            print(f"  {k}: {v}")
        
        # Check if source="a" is constant or changes
        print(f"\nObservations:")
        print(f"  - source field is always 'a' (constant)")
        print(f"  - connectionId is random (changes each prepare)")
        print(f"  - EIP712Domain is NOT in types definition")
        print(f"  - Should we construct EIP712Domain ourselves? YES")
        print(f"\nHypothesis:")
        print(f"  Nansen returns incomplete types and expects us to:")
        print(f"  1. Add the EIP712Domain type definition")
        print(f"  2. Compute domain hash from domain values and types")
        print(f"  3. Compute struct hash from message values and types")
        print(f"  4. Combine with \\x19\\x01 prefix: digest = keccak(\\x19\\x01 + domainHash + structHash)")
        print(f"  5. Sign the digest")
        print(f"\nBUT: All digests produce wrong recovered addresses!")
        print(f"\nAlternative hypothesis:")
        print(f"  Maybe Nansen doesn't use standard EIP-712?")
        print(f"  Maybe the \"eip712\" is just a message format, not actual EIP-712?")
        print(f"  Maybe we should sign: keccak(action_json + nonce + private_message)?")

asyncio.run(main())
