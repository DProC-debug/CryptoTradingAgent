"""
Test signature recovery to identify the digest/signing issue
"""
import os
from dotenv import dotenv_values
from eth_keys import keys
from eth_utils import keccak
import json

env = dotenv_values('.env')

PORTFOLIO_WALLET_PRIVATE_KEY = env['PORTFOLIO_WALLET_PRIVATE_KEY']
EXPECTED_WALLET = env['PORTFOLIO_WALLET_HYPERLIQUID']

private_key_bytes = bytes.fromhex(PORTFOLIO_WALLET_PRIVATE_KEY.lstrip("0x"))
pk = keys.PrivateKey(private_key_bytes)
# FIX: to_checksum_address() already includes 0x prefix
expected_address = pk.public_key.to_checksum_address()

print(f"Expected wallet address: {expected_address}")
print()

# Create a test message and sign it
test_message = b"test message"
test_digest = keccak(test_message)
test_sig = pk.sign_msg_hash(test_digest)

print(f"Test digest: 0x{test_digest.hex()}")
print(f"Signature v: {test_sig.v}")
print(f"Signature r: 0x{test_sig.r.to_bytes(32, byteorder='big').hex()}")
print(f"Signature s: 0x{test_sig.s.to_bytes(32, byteorder='big').hex()}")
print()

# Try to recover the address from the signature using eth_account
from eth_account import Account

print("Recovery attempts:")
for v_candidate in [test_sig.v, test_sig.v + 27]:
    try:
        # Format signature as bytes for recovery
        sig_bytes = bytes([v_candidate]) + test_sig.r.to_bytes(32, byteorder='big') + test_sig.s.to_bytes(32, byteorder='big')
        recovered_addr = Account.recover_message(
            message=test_message,
            signature=sig_bytes
        )
        print(f"  v={v_candidate:2d}: {recovered_addr} {'✓ MATCH' if recovered_addr.lower() == expected_address.lower() else '✗ MISMATCH'}")
    except Exception as e:
        print(f"  v={v_candidate:2d}: ERROR - {e}")

# Now test with the ACTUAL digest from the prepare response
print()
print("=" * 80)
print("Testing with the ACTUAL digest from prepare response")
print("=" * 80)
print()

# Simulate the exact digest computation from prepare
# Using the domain and message from the prepare response
domain = {'chainId': 1337, 'name': 'Exchange', 'verifyingContract': '0x0000000000000000000000000000000000000000', 'version': '1'}
message = {'source': 'a', 'connectionId': '0x9d496921963d935dbb074f8b6a53b8ab3e7f3e5839ccc5d81ab153c1e222b499'}
primary_type = 'Agent'
types = {
    'Agent': [
        {'name': 'source', 'type': 'string'},
        {'name': 'connectionId', 'type': 'bytes32'}
    ]
}

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
actual_digest = keccak(b"\x19\x01" + domain_hash + struct_hash)

print(f"Actual digest from prepare: 0x{actual_digest.hex()}")

# Sign this digest
actual_sig = pk.sign_msg_hash(actual_digest)

print(f"Signature v: {actual_sig.v}")
print(f"Signature r: 0x{actual_sig.r.to_bytes(32, byteorder='big').hex()}")
print(f"Signature s: 0x{actual_sig.s.to_bytes(32, byteorder='big').hex()}")
print()

# Try to recover
print("Recovery attempts:")
for v_candidate in [actual_sig.v, actual_sig.v + 27]:
    try:
        # Create message for recovery
        digest_bytes = actual_digest
        sig_bytes = bytes([v_candidate]) + actual_sig.r.to_bytes(32, byteorder='big') + actual_sig.s.to_bytes(32, byteorder='big')
        recovered_addr = Account.recover_message(
            message={'data': message, 'digest': digest_bytes},  # Try different formats
            signature=sig_bytes
        )
        print(f"  v={v_candidate:2d}: {recovered_addr} {'✓ MATCH' if recovered_addr.lower() == expected_address.lower() else '✗ MISMATCH'}")
    except Exception as e:
        # Fallback: try direct recovery from eth_keys using from_signature_and_message
        try:
            recovered_pubkey = keys.PublicKey.from_signature_and_message(
                signature=keys.Signature(vrs=(v_candidate, actual_sig.r, actual_sig.s)),
                message=actual_digest
            )
            recovered_addr = recovered_pubkey.to_checksum_address()
            print(f"  v={v_candidate:2d}: {recovered_addr} {'✓ MATCH' if recovered_addr.lower() == expected_address.lower() else '✗ MISMATCH'}")
        except Exception as e2:
            print(f"  v={v_candidate:2d}: ERROR - {e2}")
