"""
Try signing just the message hash without domain information
"""
import asyncio
import json
import aiohttp
from dotenv import dotenv_values
from eth_keys import keys
from eth_utils import keccak
from eth_account import Account
from eth_account.messages import encode_defunct
import hashlib

env = dotenv_values('.env')

NANSEN_API_KEY = env['NANSEN_API_KEY']
PORTFOLIO_WALLET = env['PORTFOLIO_WALLET_HYPERLIQUID']
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
        print("TESTING SIMPLE SIGNATURE METHODS")
        print("=" * 80)
        print(f"\nAction JSON: {json.dumps(action)}")
        print(f"Nonce: {nonce}")
        
        account = Account.from_key(PORTFOLIO_PK)
        pk_bytes = bytes.fromhex(PORTFOLIO_PK.lstrip("0x"))
        pk_obj = keys.PrivateKey(pk_bytes)
        
        # Method 1: Sign action+nonce as JSON string
        print(f"\n[Method 1] Sign JSON(action+nonce)")
        msg1 = json.dumps({"action": action, "nonce": nonce}, separators=(',', ':'), sort_keys=True)
        digest1 = keccak(msg1.encode())
        sig1 = pk_obj.sign_msg_hash(digest1)
        print(f"  Message: {msg1[:100]}...")
        print(f"  Digest: 0x{digest1.hex()}")
        
        # Method 2: Sign action JSON only
        print(f"\n[Method 2] Sign JSON(action only)")
        msg2 = json.dumps(action, separators=(',', ':'), sort_keys=True)
        digest2 = keccak(msg2.encode())
        sig2 = pk_obj.sign_msg_hash(digest2)
        print(f"  Message: {msg2[:100]}...")
        print(f"  Digest: 0x{digest2.hex()}")
        
        # Method 3: Sign nonce as string
        print(f"\n[Method 3] Sign nonce as string")
        msg3 = str(nonce)
        digest3 = keccak(msg3.encode())
        sig3 = pk_obj.sign_msg_hash(digest3)
        print(f"  Message: {msg3}")
        print(f"  Digest: 0x{digest3.hex()}")
        
        # Method 4: Sign action JSON + nonce as separate hashes
        print(f"\n[Method 4] Sign keccak(action_json + nonce_string)")
        msg4a = json.dumps(action, separators=(',', ':'), sort_keys=True).encode()
        msg4b = str(nonce).encode()
        digest4 = keccak(msg4a + msg4b)
        sig4 = pk_obj.sign_msg_hash(digest4)
        print(f"  Digest: 0x{digest4.hex()}")
        
        # Method 5: Sign using eth_account with plain message
        print(f"\n[Method 5] Sign with eth_account (Ethereum signed message)")
        msg5 = f"Order: {json.dumps(action)} Nonce: {nonce}"
        enc_msg = encode_defunct(text=msg5)
        sig5 = account.sign_message(enc_msg)
        print(f"  Message: {msg5[:80]}...")
        print(f"  v: {sig5.v}, r: 0x{sig5.r.to_bytes(32, byteorder='big').hex()[:16]}..., s: 0x{sig5.s.to_bytes(32, byteorder='big').hex()[:16]}...")
        
        # Test each method
        print(f"\n" + "=" * 80)
        print("TESTING WITH EXECUTE")
        print("=" * 80)
        
        test_methods = [
            ("Method 1: JSON(action+nonce)", sig1, sig1.v + 27),
            ("Method 2: JSON(action)", sig2, sig2.v + 27),
            ("Method 3: Nonce string", sig3, sig3.v + 27),
            ("Method 4: Concat action+nonce", sig4, sig4.v + 27),
            ("Method 5: eth_account signed message", sig5, sig5.v),
        ]
        
        for test_name, sig, v_val in test_methods:
            print(f"\n[{test_name}]")
            
            signature = {
                "v": v_val,
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
                    print(f"  Result: {result}")
                    break
                else:
                    error_text = await response.text()
                    try:
                        error_json = json.loads(error_text)
                        print(f"  ❌ {error_json.get('message', error_text)[:100]}")
                    except:
                        print(f"  ❌ {error_text[:100]}")

asyncio.run(main())
