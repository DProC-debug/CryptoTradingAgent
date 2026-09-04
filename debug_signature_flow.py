"""
Comprehensive debug script to trace the exact signature/execute issue
"""
import asyncio
import os
from dotenv import dotenv_values
from eth_account import Account
from eth_keys import keys
from eth_utils import keccak
import json
import aiohttp
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

env = dotenv_values('.env')

NANSEN_API_KEY = env['NANSEN_API_KEY']
PORTFOLIO_WALLET_HYPERLIQUID = env['PORTFOLIO_WALLET_HYPERLIQUID']
PORTFOLIO_WALLET_PRIVATE_KEY = env['PORTFOLIO_WALLET_PRIVATE_KEY']
NANSEN_BASE_URL = "https://api.nansen.ai/api/v1"

print("=" * 80)
print("COMPREHENSIVE SIGNATURE DEBUGGING")
print("=" * 80)

# Verify wallet/key match
private_key_bytes = bytes.fromhex(PORTFOLIO_WALLET_PRIVATE_KEY.lstrip("0x"))
pk_obj = keys.PrivateKey(private_key_bytes)
derived_wallet = "0x" + pk_obj.public_key.to_checksum_address()

print(f"\n[1] WALLET VERIFICATION")
print(f"    Expected: {PORTFOLIO_WALLET_HYPERLIQUID}")
print(f"    Derived:  {derived_wallet}")
print(f"    Match:    {derived_wallet.lower() == PORTFOLIO_WALLET_HYPERLIQUID.lower()}")

async def main():
    async with aiohttp.ClientSession() as session:
        # Step 1: Get BTC price
        print(f"\n[2] FETCHING BTC PRICE")
        async with session.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
        ) as response:
            price_data = await response.json()
            btc_price = price_data["bitcoin"]["usd"]
            print(f"    BTC Price: ${btc_price:.2f}")
        
        # Step 2: Prepare order
        print(f"\n[3] CALLING PREPARE ENDPOINT")
        prepare_payload = {
            "wallet_address": PORTFOLIO_WALLET_HYPERLIQUID,
            "coin": "BTC",
            "is_buy": True,
            "size": 0.001,  # 0.001 BTC ≈ $50
            "price": btc_price,
            "order_type": "market",
            "slippage": 0.03,
            "leverage": 20
        }
        print(f"    Payload: {json.dumps(prepare_payload, indent=2)}")
        
        async with session.post(
            f"{NANSEN_BASE_URL}/perp/order",
            json=prepare_payload,
            headers={"apikey": NANSEN_API_KEY, "Content-Type": "application/json"}
        ) as response:
            if response.status != 200:
                error = await response.text()
                print(f"    ERROR (HTTP {response.status}): {error}")
                return
            
            prepare_result = await response.json()
            print(f"    Status: OK")
        
        action = prepare_result.get("action")
        nonce = prepare_result.get("nonce")
        eip712_data = prepare_result.get("eip712")
        
        print(f"\n[4] PREPARE RESPONSE STRUCTURE")
        print(f"    Action keys: {list(action.keys()) if action else 'None'}")
        print(f"    Nonce: {nonce}")
        print(f"    EIP712 Domain: {eip712_data.get('domain') if eip712_data else 'None'}")
        print(f"    EIP712 Types: {list(eip712_data.get('types', {}).keys()) if eip712_data else 'None'}")
        print(f"    EIP712 PrimaryType: {eip712_data.get('primaryType') if eip712_data else 'None'}")
        print(f"    EIP712 Message keys: {list(eip712_data.get('message', {}).keys()) if eip712_data else 'None'}")
        
        # Step 3: Manual signing with eth_keys (fallback path)
        print(f"\n[5] MANUAL EIP-712 SIGNING (eth_keys fallback path)")
        
        types = dict(eip712_data.get("types", {}))
        domain = eip712_data.get("domain", {})
        primary_type = eip712_data.get("primaryType")
        message = eip712_data.get("message", {})
        
        print(f"    Domain values: {domain}")
        print(f"    Message values: {message}")
        
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
        
        print(f"    Domain hash: 0x{domain_hash.hex()}")
        print(f"    Struct hash: 0x{struct_hash.hex()}")
        print(f"    Digest: 0x{digest.hex()}")
        
        # Sign with eth_keys
        pk = keys.PrivateKey(private_key_bytes)
        signed = pk.sign_msg_hash(digest)
        
        print(f"\n[6] SIGNATURE COMPONENTS (eth_keys)")
        print(f"    v (raw): {signed.v}")
        print(f"    v (+ 27): {signed.v + 27}")
        print(f"    r: 0x{signed.r.to_bytes(32, byteorder='big').hex()}")
        print(f"    s: 0x{signed.s.to_bytes(32, byteorder='big').hex()}")
        
        # Try both v formats
        for v_format, v_value in [("raw", signed.v), ("v+27", signed.v + 27)]:
            print(f"\n[7] TESTING EXECUTE WITH v={v_format} ({v_value})")
            
            signature = {
                "v": v_value,
                "r": f"0x{signed.r.to_bytes(32, byteorder='big').hex()}",
                "s": f"0x{signed.s.to_bytes(32, byteorder='big').hex()}"
            }
            
            execute_payload = {
                "action": action,
                "nonce": nonce,
                "signature": signature
            }
            
            print(f"    Execute payload:")
            print(f"      action keys: {list(action.keys())}")
            print(f"      nonce: {nonce}")
            print(f"      signature.v: {signature['v']}")
            
            async with session.post(
                f"{NANSEN_BASE_URL}/perp/execute",
                json=execute_payload,
                headers={"apikey": NANSEN_API_KEY, "Content-Type": "application/json"}
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    print(f"    ✅ SUCCESS: {json.dumps(result, indent=2)}")
                    break
                else:
                    error = await response.text()
                    print(f"    ❌ FAILED (HTTP {response.status}): {error}")

asyncio.run(main())
