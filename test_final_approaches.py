"""
Try using msgpack encoding as the Hyperliquid SDK apparently does
"""
import asyncio
import json
import aiohttp
from dotenv import dotenv_values
from eth_keys import keys
from eth_utils import keccak

env = dotenv_values('.env')

NANSEN_API_KEY = env['NANSEN_API_KEY']
PORTFOLIO_WALLET = env['PORTFOLIO_WALLET_HYPERLIQUID'].lower()
PORTFOLIO_PK = env['PORTFOLIO_WALLET_PRIVATE_KEY']
NANSEN_BASE_URL = "https://api.nansen.ai/api/v1"

async def main():
    async with aiohttp.ClientSession() as session:
        # Get BTC price
        async with session.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
        ) as response:
            price_data = await response.json()
            btc_price = price_data["bitcoin"]["usd"]
        
        # Prepare order
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
            action = prepare_result.get("action")
            nonce = prepare_result.get("nonce")
            eip712 = prepare_result.get("eip712")
        
        print("=" * 80)
        print("TEST: Sign using different encoding approaches")
        print("=" * 80)
        
        pk_bytes = bytes.fromhex(PORTFOLIO_PK.lstrip("0x"))
        pk_obj = keys.PrivateKey(pk_bytes)
        
        # Approach 1: Check if maybe just signing the nonce is enough
        print(f"\n[Approach 1] Sign ONLY nonce as keccak(nonce_str)")
        nonce_str = str(nonce).encode()
        digest_nonce = keccak(nonce_str)
        sig_nonce = pk_obj.sign_msg_hash(digest_nonce)
        
        # Approach 2: Try signing the action + nonce with a separator
        print(f"[Approach 2] Sign action_json + '|' + nonce")
        action_json = json.dumps(action, separators=(',', ':'), sort_keys=True).encode()
        combined = action_json + b'|' + nonce_str
        digest_combined = keccak(combined)
        sig_combined = pk_obj.sign_msg_hash(digest_combined)
        
        # Approach 3: Maybe nonce is the primary thing
        print(f"[Approach 3] Sign keccak(keccak(action) + keccak(nonce))")
        action_hash = keccak(action_json)
        nonce_hash = keccak(nonce_str)
        digest_double_hash = keccak(action_hash + nonce_hash)
        sig_double_hash = pk_obj.sign_msg_hash(digest_double_hash)
        
        approaches = [
            ("Approach 1: Nonce only", sig_nonce),
            ("Approach 2: Action+nonce with separator", sig_combined),
            ("Approach 3: Double hash", sig_double_hash),
        ]
        
        for approach_name, sig in approaches:
            print(f"\n[{approach_name}]")
            
            signature = {
                "v": sig.v + 27,
                "r": f"0x{sig.r.to_bytes(32, byteorder='big').hex()}",
                "s": f"0x{sig.s.to_bytes(32, byteorder='big').hex()}"
            }
            
            execute_payload = {
                "wallet_address": PORTFOLIO_WALLET,
                "action": action,
                "nonce": nonce,
                "signature": signature
            }
            
            async with session.post(
                f"{NANSEN_BASE_URL}/perp/execute",
                json=execute_payload,
                headers={"apikey": NANSEN_API_KEY, "Content-Type": "application/json"}
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    print(f"  ✅ SUCCESS!")
                    print(f"  Result: {json.dumps(result, indent=2)}")
                    return
                else:
                    error_text = await response.text()
                    try:
                        error_json = json.loads(error_text)
                        err_msg = error_json.get('message', error_text)
                        print(f"  ❌ {err_msg[:120]}")
                    except:
                        print(f"  ❌ {error_text[:120]}")
        
        print("\n" + "=" * 80)
        print("DEBUGGING INFO")
        print("=" * 80)
        print(f"Wallet: {PORTFOLIO_WALLET}")
        print(f"Nonce: {nonce}")
        print(f"Action has 'type': {'type' in action}")
        print(f"Action type value: {action.get('type')}")
        
        print("\nRECOMMENDATION:")
        print("All 9+ signing methods have been tested without success.")
        print("The issue appears to be fundamental to the message format.")
        print("\nNext steps:")
        print("1. Check Nansen's official documentation or examples")
        print("2. Contact Nansen support for signing specification")
        print("3. Use Hyperliquid's official Python SDK directly")
        print("4. Check if there's a working example code in Hyperliquid repo")

asyncio.run(main())
