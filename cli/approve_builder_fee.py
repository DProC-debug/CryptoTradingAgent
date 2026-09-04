#!/usr/bin/env python3
"""
One-Command Builder Fee Approval for Hyperliquid
Checks status -> Requests EIP712 -> Signs locally -> Executes approval
"""

import asyncio
import json
import sys
from typing import Optional

try:
    from eth_account import Account
    from eth_keys import keys
    from eth_utils import keccak
    import aiohttp
except ImportError as e:
    print(f"ERROR: Required packages not installed: {e}")
    sys.exit(1)

from dotenv import load_dotenv
import os

load_dotenv()


def hash_eip712_struct(primary_type: str, message: dict, types: dict) -> bytes:
    """Hash an EIP712 struct according to the standard"""
    
    def get_type_string(type_name: str) -> str:
        """Get the type definition string"""
        if type_name not in types:
            return type_name
        
        fields_data = types[type_name]
        
        # Handle both formats: array of objects and dict
        if isinstance(fields_data, list):
            field_strings = [f"{field['type']} {field['name']}" for field in fields_data]
        else:
            field_strings = [f"{field_type} {field_name}" for field_name, field_type in fields_data.items()]
        
        return f"{type_name}({','.join(field_strings)})"
    
    # Hash the type string
    type_string = get_type_string(primary_type)
    type_hash = keccak(text=type_string)
    
    def encode_field(field_name: str, field_type: str, value) -> bytes:
        """Encode a single field value"""
        if field_type == "string":
            return keccak(text=value)
        elif field_type == "bytes":
            return keccak(value)
        elif field_type.startswith("uint"):
            if isinstance(value, str):
                value = int(value)
            return value.to_bytes(32, byteorder='big')
        elif field_type == "address":
            if isinstance(value, str) and value.startswith("0x"):
                return bytes.fromhex(value[2:].zfill(40))
            return bytes.fromhex(value.zfill(40))
        elif field_type.startswith("bool"):
            return b"\x01" if value else b"\x00"
        else:
            return hash_eip712_struct(field_type, value, types)
    
    # Build encoded fields
    encoded_fields = [type_hash]
    
    fields_data = types[primary_type]
    if isinstance(fields_data, list):
        for field in fields_data:
            field_name = field["name"]
            field_type = field["type"]
            encoded_fields.append(encode_field(field_name, field_type, message[field_name]))
    else:
        for field_name, field_type in fields_data.items():
            encoded_fields.append(encode_field(field_name, field_type, message[field_name]))
    
    return keccak(b"".join(encoded_fields))


def sign_eip712(private_key: str, eip712_payload: dict) -> tuple:
    """Sign an EIP712 message and return (r, s, v)"""
    
    if not private_key.startswith("0x"):
        private_key = "0x" + private_key
    
    account = Account.from_key(private_key)
    print(f"[OK] Signing with address: {account.address}")
    
    domain = eip712_payload.get("domain", {})
    primary_type = eip712_payload.get("primaryType", "")
    message = eip712_payload.get("message", {})
    types = eip712_payload.get("types", {})
    
    # Hash domain and struct
    domain_hash = hash_eip712_struct("EIP712Domain", domain, types)
    struct_hash = hash_eip712_struct(primary_type, message, types)
    
    # Combine hashes with prefix
    digest = keccak(b"\x19\x01" + domain_hash + struct_hash)
    print(f"[OK] EIP712 message hashed")
    
    # Sign the digest
    private_key_bytes = bytes.fromhex(private_key.lstrip("0x"))
    private_key_obj = keys.PrivateKey(private_key_bytes)
    signed = private_key_obj.sign_msg_hash(digest)
    
    print(f"[OK] Message signed successfully")
    
    return hex(signed.r), hex(signed.s), signed.v


async def approve_builder_fee(private_key: str, wallet_address: str, api_key: str):
    """
    Complete builder fee approval flow in one command
    1. Check status
    2. Request approval (EIP712)
    3. Sign locally
    4. Execute approval
    """
    
    base_url = "https://api.nansen.ai/api/v1"
    headers = {"apikey": api_key, "Content-Type": "application/json"}
    
    async with aiohttp.ClientSession() as session:
        # STEP 1: Check current status
        print("\n" + "="*70)
        print("[STEP 1/4] Checking builder fee status...")
        print("="*70)
        
        try:
            async with session.get(
                f"{base_url}/perp/builder-fee",
                params={"wallet_address": wallet_address},
                headers=headers
            ) as resp:
                if resp.status == 200:
                    status = await resp.json()
                    print(f"[OK] Approval Status: {status.get('approved')}")
                    print(f"    Required fee: {status.get('required_fee')}")
                    
                    if status.get("approved"):
                        print("\n[OK] Builder fee already approved! Ready to trade.")
                        return True
                else:
                    print(f"[ERROR] Failed to check status: {resp.status}")
                    return False
        except Exception as e:
            print(f"[ERROR] Status check failed: {e}")
            return False
        
        # STEP 2: Request approval
        print("\n" + "="*70)
        print("[STEP 2/4] Requesting builder fee approval...")
        print("="*70)
        
        try:
            async with session.post(
                f"{base_url}/perp/approve-builder-fee",
                json={"wallet_address": wallet_address},
                headers=headers
            ) as resp:
                if resp.status == 200:
                    approval_data = await resp.json()
                    print(f"[OK] Approval request prepared")
                    print(f"    Nonce: {approval_data.get('nonce')}")
                else:
                    error = await resp.text()
                    print(f"[ERROR] Failed to request approval: {error}")
                    return False
        except Exception as e:
            print(f"[ERROR] Approval request failed: {e}")
            return False
        
        # STEP 3: Sign locally
        print("\n" + "="*70)
        print("[STEP 3/4] Signing locally...")
        print("="*70)
        
        try:
            r, s, v = sign_eip712(private_key, approval_data)
            signature = {"r": r, "s": s, "v": v}
            print(f"[OK] Signature generated")
            print(f"    r: {r}")
            print(f"    s: {s}")
            print(f"    v: {v}")
        except Exception as e:
            print(f"[ERROR] Signing failed: {e}")
            import traceback
            traceback.print_exc()
            return False
        
        # STEP 4: Execute approval
        print("\n" + "="*70)
        print("[STEP 4/4] Executing approval...")
        print("="*70)
        
        try:
            payload = {
                "action": approval_data.get("action"),
                "nonce": approval_data.get("nonce"),
                "signature": signature
            }
            
            async with session.post(
                f"{base_url}/perp/execute",
                json=payload,
                headers=headers
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    print(f"[OK] Builder fee approval executed successfully!")
                    print(f"    Transaction hash: {result.get('tx_hash')}")
                    print("\n" + "="*70)
                    print("[SUCCESS] Your wallet is now approved for trading!")
                    print("="*70)
                    return True
                else:
                    error = await resp.text()
                    print(f"[ERROR] Execution failed (HTTP {resp.status}): {error}")
                    return False
        except Exception as e:
            print(f"[ERROR] Execution failed: {e}")
            return False


def main():
    """Main entry point"""
    print("\n" + "="*70)
    print("HYPERLIQUID BUILDER FEE APPROVAL")
    print("="*70)
    
    # Get private key
    if len(sys.argv) < 2:
        print("\nUsage:")
        print("  python cli/approve_builder_fee.py <private_key>")
        print("\nExample:")
        print("  python cli/approve_builder_fee.py 0000000000000000000000000000000000000000000000000000000000000000")
        print("\nThe script will:")
        print("  1. Check current approval status")
        print("  2. Request approval (if needed)")
        print("  3. Sign locally with your private key")
        print("  4. Execute the approval")
        print("\n[WARNING] Your private key is only used locally and never sent anywhere!")
        print("="*70)
        sys.exit(1)
    
    private_key = sys.argv[1]
    
    # Get config from .env
    api_key = os.getenv("NANSEN_API_KEY")
    wallet_address = os.getenv("PORTFOLIO_WALLET_HYPERLIQUID")
    
    if not api_key:
        print("[ERROR] NANSEN_API_KEY not found in .env")
        sys.exit(1)
    
    if not wallet_address:
        print("[ERROR] PORTFOLIO_WALLET_HYPERLIQUID not found in .env")
        sys.exit(1)
    
    print(f"\n[INFO] Using wallet: {wallet_address[:10]}...")
    print(f"[INFO] Using API key: {api_key[:10]}...")
    
    # Run approval flow
    try:
        success = asyncio.run(approve_builder_fee(private_key, wallet_address, api_key))
        
        if success:
            print("\n[OK] You can now restart your trading agent:")
            print("  python cli/autonomous_trader.py")
            sys.exit(0)
        else:
            print("\n[ERROR] Approval failed. Please check the errors above.")
            sys.exit(1)
    
    except KeyboardInterrupt:
        print("\n[CANCELLED] Approval cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
