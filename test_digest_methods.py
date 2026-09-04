"""
Test different EIP-712 digest computation methods to find what Nansen expects
"""
import asyncio
import json
import aiohttp
from dotenv import dotenv_values
from eth_keys import keys
from eth_utils import keccak
from eth_account import Account
from eth_account.messages import encode_typed_data

env = dotenv_values('.env')

NANSEN_API_KEY = env['NANSEN_API_KEY']
PORTFOLIO_WALLET = env['PORTFOLIO_WALLET_HYPERLIQUID']
PORTFOLIO_PK = env['PORTFOLIO_WALLET_PRIVATE_KEY']
NANSEN_BASE_URL = "https://api.nansen.ai/api/v1"

def hash_eip712_struct(struct_name, data, types_dict):
    """Standard EIP-712 struct hashing"""
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
        print("TESTING DIFFERENT EIP-712 DIGEST COMPUTATION METHODS")
        print("=" * 80)
        print(f"\nNonce: {nonce}")
        print(f"EIP712 Message: {json.dumps(eip712.get('message', {}), indent=2)}")
        print(f"EIP712 Domain: {json.dumps(eip712.get('domain', {}), indent=2)}")
        
        pk_bytes = bytes.fromhex(PORTFOLIO_PK.lstrip("0x"))
        pk = keys.PrivateKey(pk_bytes)
        account = Account.from_key(PORTFOLIO_PK)
        
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
        
        # Method 1: Standard EIP-712 with \x19\x01 prefix
        print(f"\n[Method 1] Standard EIP-712 with domain + struct")
        domain_hash = hash_eip712_struct("EIP712Domain", eip712.get("domain", {}), types_with_domain)
        struct_hash = hash_eip712_struct(eip712.get("primaryType"), eip712.get("message", {}), types_with_domain)
        digest1 = keccak(b"\x19\x01" + domain_hash + struct_hash)
        sig1 = pk.sign_msg_hash(digest1)
        print(f"  Digest: 0x{digest1.hex()}")
        print(f"  Signature v: {sig1.v + 27}")
        
        # Method 2: Just struct hash (no domain, no prefix)
        print(f"\n[Method 2] Just struct hash (no domain, no prefix)")
        struct_hash_only = hash_eip712_struct(eip712.get("primaryType"), eip712.get("message", {}), types_with_domain)
        digest2 = struct_hash_only
        sig2 = pk.sign_msg_hash(digest2)
        print(f"  Digest: 0x{digest2.hex()}")
        print(f"  Signature v: {sig2.v + 27}")
        
        # Method 3: Just struct hash with \x19\x01 prefix
        print(f"\n[Method 3] Struct hash with \\x19\\x01 prefix")
        digest3 = keccak(b"\x19\x01" + struct_hash_only)
        sig3 = pk.sign_msg_hash(digest3)
        print(f"  Digest: 0x{digest3.hex()}")
        print(f"  Signature v: {sig3.v + 27}")
        
        # Method 4: Using eth_account's encode_typed_data (if it works)
        print(f"\n[Method 4] eth_account.encode_typed_data")
        try:
            msg = encode_typed_data(eip712)
            sig4 = account.sign_message(msg)
            print(f"  eth_account signing succeeded")
            print(f"  Signature v: {sig4.v}")
        except Exception as e:
            print(f"  eth_account signing failed: {e}")
        
        # Now test each method
        print(f"\n" + "=" * 80)
        print("TESTING EACH DIGEST WITH EXECUTE")
        print("=" * 80)
        
        test_cases = [
            ("Method 1 (domain+struct, v+27)", digest1, sig1, sig1.v + 27),
            ("Method 2 (struct only, no prefix, v+27)", digest2, sig2, sig2.v + 27),
            ("Method 3 (struct+prefix, v+27)", digest3, sig3, sig3.v + 27),
        ]
        
        for test_name, digest, sig, v_value in test_cases:
            print(f"\n[{test_name}]")
            
            signature = {
                "v": v_value,
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
                    error_json = json.loads(error_text)
                    print(f"  ❌ Failed: {error_json.get('message', error_text)}")

asyncio.run(main())
