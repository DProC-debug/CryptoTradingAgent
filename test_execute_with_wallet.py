"""
Test execute endpoint with explicit wallet_address parameter
"""
import asyncio
import os
from dotenv import dotenv_values
from eth_keys import keys
from eth_utils import keccak
import json
import aiohttp

env = dotenv_values('.env')

NANSEN_API_KEY = env['NANSEN_API_KEY']
PORTFOLIO_WALLET_HYPERLIQUID = env['PORTFOLIO_WALLET_HYPERLIQUID']
PORTFOLIO_WALLET_PRIVATE_KEY = env['PORTFOLIO_WALLET_PRIVATE_KEY']
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
        nonce = prepare_result.get("nonce")
        eip712_data = prepare_result.get("eip712")
        
        print(f"Prepare successful")
        print(f"  Nonce: {nonce}")
        
        # Sign the payload
        private_key_bytes = bytes.fromhex(PORTFOLIO_WALLET_PRIVATE_KEY.lstrip("0x"))
        pk = keys.PrivateKey(private_key_bytes)
        
        types = dict(eip712_data.get("types", {}))
        domain = eip712_data.get("domain", {})
        primary_type = eip712_data.get("primaryType")
        message = eip712_data.get("message", {})
        
        def hash_eip712_struct(struct_name, data, types_dict):
            """Hash an EIP-712 struct"""
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
        
        domain_types = {
            "EIP712Domain": [
                {"name": "chainId", "type": "uint256"},
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "verifyingContract", "type": "address"},
            ]
        }
        types_with_domain = {**domain_types, **types}
        
        domain_hash = hash_eip712_struct("EIP712Domain", domain, types_with_domain)
        struct_hash = hash_eip712_struct(primary_type, message, types_with_domain)
        digest = keccak(b"\x19\x01" + domain_hash + struct_hash)
        
        signed = pk.sign_msg_hash(digest)
        
        print(f"Signing successful")
        print(f"  Signature v: {signed.v}")
        
        # TEST 1: Current format (no wallet_address)
        print(f"\n[TEST 1] Execute WITHOUT wallet_address")
        signature = {
            "v": signed.v + 27,  # Adjust v to 27/28
            "r": f"0x{signed.r.to_bytes(32, byteorder='big').hex()}",
            "s": f"0x{signed.s.to_bytes(32, byteorder='big').hex()}"
        }
        
        execute_payload_1 = {
            "action": action,
            "nonce": nonce,
            "signature": signature
        }
        
        async with session.post(
            f"{NANSEN_BASE_URL}/perp/execute",
            json=execute_payload_1,
            headers={"apikey": NANSEN_API_KEY, "Content-Type": "application/json"}
        ) as response:
            if response.status == 200:
                print(f"  ✅ SUCCESS")
                result = await response.json()
                print(f"  Result: {result}")
            else:
                error = await response.text()
                print(f"  ❌ FAILED: {error}")
        
        # TEST 2: With wallet_address
        print(f"\n[TEST 2] Execute WITH wallet_address")
        execute_payload_2 = {
            "wallet_address": PORTFOLIO_WALLET_HYPERLIQUID,
            "action": action,
            "nonce": nonce,
            "signature": signature
        }
        
        async with session.post(
            f"{NANSEN_BASE_URL}/perp/execute",
            json=execute_payload_2,
            headers={"apikey": NANSEN_API_KEY, "Content-Type": "application/json"}
        ) as response:
            if response.status == 200:
                print(f"  ✅ SUCCESS")
                result = await response.json()
                print(f"  Result: {result}")
            else:
                error = await response.text()
                print(f"  ❌ FAILED: {error}")
        
        # TEST 3: With v=raw (0 or 1 instead of +27)
        print(f"\n[TEST 3] Execute WITH wallet_address and v={signed.v} (raw)")
        signature_raw = {
            "v": signed.v,
            "r": f"0x{signed.r.to_bytes(32, byteorder='big').hex()}",
            "s": f"0x{signed.s.to_bytes(32, byteorder='big').hex()}"
        }
        
        execute_payload_3 = {
            "wallet_address": PORTFOLIO_WALLET_HYPERLIQUID,
            "action": action,
            "nonce": nonce,
            "signature": signature_raw
        }
        
        async with session.post(
            f"{NANSEN_BASE_URL}/perp/execute",
            json=execute_payload_3,
            headers={"apikey": NANSEN_API_KEY, "Content-Type": "application/json"}
        ) as response:
            if response.status == 200:
                print(f"  ✅ SUCCESS")
                result = await response.json()
                print(f"  Result: {result}")
            else:
                error = await response.text()
                print(f"  ❌ FAILED: {error}")

asyncio.run(main())
