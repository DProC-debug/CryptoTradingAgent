#!/usr/bin/env python3
"""
EIP712 Signature Helper for Hyperliquid Builder Fee Approval
Use this to sign the EIP712 payload from the trading agent
"""

import json
import os
import sys
from typing import Dict, Tuple

from dotenv import load_dotenv

load_dotenv()

try:
    from eth_account import Account
    from eth_keys import keys
    from eth_utils import keccak
except ImportError as e:
    print(f"ERROR: Required packages not installed: {e}")
    sys.exit(1)


def hash_eip712_struct(primary_type: str, message: Dict, types: Dict) -> bytes:
    """Hash an EIP712 struct according to the standard"""
    
    # Build type string
    def get_type_string(type_name: str) -> str:
        """Get the type definition string"""
        if type_name not in types:
            return type_name
        
        fields_data = types[type_name]
        
        # Handle both formats: array of objects and dict
        if isinstance(fields_data, list):
            # Format: [{"name": "field1", "type": "string"}, ...]
            field_strings = [f"{field['type']} {field['name']}" for field in fields_data]
        else:
            # Format: {"field1": "string", ...}
            field_strings = [f"{field_type} {field_name}" for field_name, field_type in fields_data.items()]
        
        return f"{type_name}({','.join(field_strings)})"
    
    # Hash the type string
    type_string = get_type_string(primary_type)
    type_hash = keccak(text=type_string)
    
    # Encode struct fields
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
            # For complex types, recursively hash
            return hash_eip712_struct(field_type, value, types)
    
    # Build encoded fields
    encoded_fields = [type_hash]
    
    fields_data = types[primary_type]
    
    # Handle both formats: array of objects and dict
    if isinstance(fields_data, list):
        # Format: [{"name": "field1", "type": "string"}, ...]
        for field in fields_data:
            field_name = field["name"]
            field_type = field["type"]
            encoded_fields.append(encode_field(field_name, field_type, message[field_name]))
    else:
        # Format: {"field1": "string", ...}
        for field_name, field_type in fields_data.items():
            encoded_fields.append(encode_field(field_name, field_type, message[field_name]))
    
    return keccak(b"".join(encoded_fields))


def hash_eip712_domain(domain: Dict, types: Dict) -> bytes:
    """Hash an EIP712 domain"""
    return hash_eip712_struct("EIP712Domain", domain, types)


def sign_eip712(private_key: str, eip712_payload: Dict) -> Tuple[str, str, int]:
    """
    Sign an EIP712 message with a private key
    
    Args:
        private_key: Private key (with or without 0x prefix)
        eip712_payload: The EIP712 message dict with types, domain, primaryType, message
        
    Returns:
        Tuple of (r, s, v) signature components
    """
    try:
        # Ensure private key has 0x prefix
        if not private_key.startswith("0x"):
            private_key = "0x" + private_key
        
        # Create account from private key
        account = Account.from_key(private_key)
        print(f"[OK] Signing with address: {account.address}")
        
        # Extract components
        domain = eip712_payload.get("domain", {})
        primary_type = eip712_payload.get("primaryType", "")
        message = eip712_payload.get("message", {})
        types = eip712_payload.get("types", {})
        
        print(f"[OK] EIP712 message extracted")
        print(f"    Domain: {domain.get('name', 'unknown')}")
        print(f"    Type: {primary_type}")
        
        # Hash domain and struct
        domain_hash = hash_eip712_domain(domain, types)
        struct_hash = hash_eip712_struct(primary_type, message, types)
        
        # Combine hashes with prefix
        digest = keccak(b"\x19\x01" + domain_hash + struct_hash)
        print(f"[OK] EIP712 message hashed")
        
        # Sign the digest
        private_key_bytes = bytes.fromhex(private_key.lstrip("0x"))
        private_key_obj = keys.PrivateKey(private_key_bytes)
        signed = private_key_obj.sign_msg_hash(digest)
        
        print(f"[OK] Message signed successfully")
        
        # Extract signature components
        r = hex(signed.r)
        s = hex(signed.s)
        v = signed.v
        
        print(f"\n[SIGNATURE]")
        print(f"  r: {r}")
        print(f"  s: {s}")
        print(f"  v: {v}")
        
        return r, s, v
    
    except Exception as e:
        print(f"[ERROR] Signing failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def main():
    """Main entry point"""
    print("=" * 70)
    print("EIP712 SIGNATURE HELPER FOR HYPERLIQUID BUILDER FEE APPROVAL")
    print("=" * 70)
    
    private_key = os.getenv("PORTFOLIO_WALLET_PRIVATE_KEY")
    if not private_key:
        print("\n[ERROR] PORTFOLIO_WALLET_PRIVATE_KEY not found in .env")
        print("\nUsage:")
        print("  python cli/sign_eip712.py [payload.json]")
        print("\nThe private key is read from PORTFOLIO_WALLET_PRIVATE_KEY in .env - never pass it on the command line.")
        print("=" * 70)
        sys.exit(1)

    # Try to read from stdin first
    print("\nMethod 1: Paste JSON directly (paste then press Ctrl+D on Unix or Ctrl+Z on Windows):")
    print("Method 2: Save to file and pass as argument: python cli/sign_eip712.py payload.json")
    print()

    eip712_payload = None

    # Check if a file argument was provided
    if len(sys.argv) > 1:
        payload_file = sys.argv[1]
        try:
            with open(payload_file, 'r') as f:
                eip712_payload = json.load(f)
            print(f"[OK] Loaded payload from {payload_file}")
        except Exception as e:
            print(f"[ERROR] Failed to load file: {e}")
            sys.exit(1)
    else:
        # Try stdin with timeout
        print("Waiting for EIP712 payload (paste JSON):\n")
        
        lines = []
        try:
            
            # On Windows, select doesn't work the same way, so use a simpler approach
            if sys.platform == "win32":
                print("[INFO] Windows detected. Paste the JSON payload:")
                print("[INFO] After pasting, press Enter twice to finish\n")
                
                empty_line_count = 0
                while empty_line_count < 2:
                    line = sys.stdin.readline()
                    if not line:
                        break
                    if line.strip() == "":
                        empty_line_count += 1
                    else:
                        empty_line_count = 0
                        lines.append(line)
            else:
                # Unix/Linux/Mac
                print("[INFO] Paste the JSON payload:")
                print("[INFO] Press Ctrl+D when done\n")
                lines = sys.stdin.readlines()
            
            eip712_json = "".join(lines).strip()
            if not eip712_json:
                print("[ERROR] No input received")
                print("\nAlternative: Save payload to a file and run:")
                print("  python cli/sign_eip712.py payload.json")
                sys.exit(1)
            
            eip712_payload = json.loads(eip712_json)
            print("[OK] Payload received\n")
        
        except json.JSONDecodeError as e:
            print(f"[ERROR] Invalid JSON: {e}")
            sys.exit(1)
        except KeyboardInterrupt:
            print("\n[ERROR] Cancelled by user")
            sys.exit(1)
        except Exception as e:
            print(f"[ERROR] Failed to read input: {e}")
            print("\nAlternative: Save payload to a file and run:")
            print("  python cli/sign_eip712.py payload.json")
            sys.exit(1)
    
    # Sign the payload
    r, s, v = sign_eip712(private_key, eip712_payload)
    
    # Print the signature in the format expected by the API
    signature_dict = {
        "r": r,
        "s": s,
        "v": v
    }
    
    print(f"\n[COPY THIS TO THE AGENT]")
    print(json.dumps(signature_dict, indent=2))


if __name__ == "__main__":
    main()
