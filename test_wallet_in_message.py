"""
Test if wallet_address needs to be included in the message being signed
"""
import asyncio
import json
import aiohttp
from dotenv import dotenv_values
from eth_keys import keys
from eth_utils import keccak

env = dotenv_values('.env')

NANSEN_API_KEY = env['NANSEN_API_KEY']
PORTFOLIO_WALLET = env['PORTFOLIO_WALLET_HYPERLIQUID'].lower()  # Lowercase!
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
        print("TEST: Include wallet_address in message being signed")
        print("=" * 80)
        print(f"\nWallet (lowercase): {PORTFOLIO_WALLET}")
        print(f"Nonce: {nonce}")
        
        pk_bytes = bytes.fromhex(PORTFOLIO_PK.lstrip("0x"))
        pk_obj = keys.PrivateKey(pk_bytes)
        
        # Standard EIP-712 with domain + struct
        def hash_eip712_struct(struct_name, data, types_dict):
            struct_types = types_dict.get(struct_name, [])
            type_hash = keccak(
                "".join([f"{field['name']}({field['type']})" for field in struct_types]).encode()
            )
            encoded_fields = [type_hash]
            for field in struct_types:
                field_name = field['name']
                field_type = field['type']
                field_value = data.get(field_name)
                
                if field_type == "string":
                    encoded = keccak(field_value.encode() if isinstance(field_value, str) else field_value)
                elif field_type == "address":
                    encoded = bytes.fromhex(field_value.lstrip("0x")).rjust(32, b'\x00')
                elif field_type == "uint256":
                    encoded = field_value.to_bytes(32, byteorder='big') if isinstance(field_value, int) else bytes.fromhex(str(field_value).lstrip("0x")).rjust(32, b'\x00')
                elif field_type == "bytes32":
                    encoded = bytes.fromhex(field_value.lstrip("0x")).rjust(32, b'\x00')
                else:
                    encoded = field_value.encode() if isinstance(field_value, str) else field_value
                
                encoded_fields.append(encoded)
            
            return keccak(b"".join(encoded_fields))
        
        types_dict = eip712.get("types", {})
        types_with_domain = {
            "EIP712Domain": [
                {"name": "chainId", "type": "uint256"},
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "verifyingContract", "type": "address"},
            ],
            **types_dict
        }
        
        # Test 1: Standard way (no wallet in message)
        print(f"\n[Test 1] Standard EIP-712 (wallet NOT in message)")
        domain_hash = hash_eip712_struct("EIP712Domain", eip712.get("domain", {}), types_with_domain)
        struct_hash = hash_eip712_struct(eip712.get("primaryType"), eip712.get("message", {}), types_with_domain)
        digest1 = keccak(b"\x19\x01" + domain_hash + struct_hash)
        sig1 = pk_obj.sign_msg_hash(digest1)
        
        # Test 2: Include wallet in the action before signing
        print(f"\n[Test 2] Sign action WITH wallet_address added")
        action_with_wallet = dict(action)
        action_with_wallet["wallet_address"] = PORTFOLIO_WALLET
        msg2 = json.dumps(action_with_wallet, separators=(',', ':'), sort_keys=True)
        digest2 = keccak(msg2.encode())
        sig2 = pk_obj.sign_msg_hash(digest2)
        
        # Test 3: Sign as "wallet_address + action + nonce"
        print(f"\n[Test 3] Sign concatenation: wallet + action + nonce")
        msg3 = PORTFOLIO_WALLET + json.dumps(action, separators=(',', ':'), sort_keys=True) + str(nonce)
        digest3 = keccak(msg3.encode())
        sig3 = pk_obj.sign_msg_hash(digest3)
        
        tests = [
            ("Test 1: Standard EIP-712", sig1),
            ("Test 2: Action with wallet", sig2),
            ("Test 3: Wallet+action+nonce", sig3),
        ]
        
        for test_name, sig in tests:
            print(f"\n[{test_name}]")
            
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

asyncio.run(main())
