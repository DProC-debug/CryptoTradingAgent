"""
Direct inline test of the fix - tests execute with wallet_address parameter
"""
import asyncio
import json
import aiohttp
from dotenv import dotenv_values
from eth_keys import keys
from eth_utils import keccak

env = dotenv_values('.env')

NANSEN_API_KEY = env['NANSEN_API_KEY']
PORTFOLIO_WALLET = env['PORTFOLIO_WALLET_HYPERLIQUID']
PORTFOLIO_PK = env['PORTFOLIO_WALLET_PRIVATE_KEY']
NANSEN_BASE_URL = "https://api.nansen.ai/api/v1"

async def main():
    async with aiohttp.ClientSession() as session:
        print("=" * 80)
        print("INLINE TEST: Execute with wallet_address")
        print("=" * 80)
        
        # Get BTC price
        async with session.get(
            "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd"
        ) as response:
            price_data = await response.json()
            btc_price = price_data["bitcoin"]["usd"]
        
        print(f"\n[1] BTC Price: ${btc_price:.2f}")
        
        # Check account balance
        print(f"\n[2] Checking account balance...")
        async with session.get(
            f"{NANSEN_BASE_URL}/perp/account",
            params={"wallet_address": PORTFOLIO_WALLET},
            headers={"apikey": NANSEN_API_KEY}
        ) as response:
            account_data = await response.json()
            spot_usdc = float(account_data.get("spotUsdc", 0))
            perp_usdc = float(account_data.get("marginSummary", {}).get("accountValue", 0))
            total_usdc = spot_usdc + perp_usdc
            print(f"    Spot USDC: ${spot_usdc:.2f}")
            print(f"    Perp USDC: ${perp_usdc:.2f}")
            print(f"    Total USDC: ${total_usdc:.2f}")
        
        if total_usdc < 50:
            print(f"\n❌ Insufficient balance for $50 order")
            return
        
        # Prepare order
        print(f"\n[3] Preparing order...")
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
            if response.status != 200:
                error = await response.text()
                print(f"    ❌ Prepare failed: {error}")
                return
            
            prepare_result = await response.json()
            action = prepare_result.get("action")
            nonce = prepare_result.get("nonce")
            eip712 = prepare_result.get("eip712")
            print(f"    ✅ Prepare successful, nonce={nonce}")
        
        # Sign
        print(f"\n[4] Signing EIP-712 message...")
        pk_bytes = bytes.fromhex(PORTFOLIO_PK.lstrip("0x"))
        pk = keys.PrivateKey(pk_bytes)
        
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
        
        domain_hash = hash_eip712_struct("EIP712Domain", eip712.get("domain", {}), types_with_domain)
        struct_hash = hash_eip712_struct(eip712.get("primaryType"), eip712.get("message", {}), types_with_domain)
        digest = keccak(b"\x19\x01" + domain_hash + struct_hash)
        
        sig = pk.sign_msg_hash(digest)
        signature = {
            "v": sig.v + 27,  # Convert to standard format
            "r": f"0x{sig.r.to_bytes(32, byteorder='big').hex()}",
            "s": f"0x{sig.s.to_bytes(32, byteorder='big').hex()}"
        }
        print(f"    ✅ Signed, v={signature['v']}")
        
        # Execute WITH wallet_address
        print(f"\n[5] Executing order WITH wallet_address...")
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
                print(f"    ✅ SUCCESS!")
                print(f"    Result: {json.dumps(result, indent=2)}")
            else:
                error = await response.text()
                print(f"    ❌ FAILED (HTTP {response.status})")
                print(f"    Error: {error}")

asyncio.run(main())
