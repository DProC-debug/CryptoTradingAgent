"""
Direct verification that private key correctly derives to wallet
"""
import os
from dotenv import dotenv_values
from eth_account import Account
from eth_keys import keys
from hexbytes import HexBytes
from web3 import Web3

env = dotenv_values('.env')

wallet = env['PORTFOLIO_WALLET_HYPERLIQUID']
pk_hex = env['PORTFOLIO_WALLET_PRIVATE_KEY']

print("=" * 80)
print("PRIVATE KEY VALIDATION")
print("=" * 80)

print(f"\nExpected wallet: {wallet}")
print(f"Private key (first 10 chars): {pk_hex[:10]}...")

# Method 1: Using eth_account
print("\n[Method 1] eth_account.Account")
account = Account.from_key(pk_hex)
derived_addr_1 = account.address
print(f"  Derived: {derived_addr_1}")
print(f"  Match: {derived_addr_1.lower() == wallet.lower()}")

# Method 2: Using eth_keys
print("\n[Method 2] eth_keys.PrivateKey")
private_key_bytes = bytes.fromhex(pk_hex.lstrip("0x"))
pk = keys.PrivateKey(private_key_bytes)
derived_addr_2 = pk.public_key.to_checksum_address()
print(f"  Derived: {derived_addr_2}")
print(f"  Match: {derived_addr_2.lower() == wallet.lower()}")

# Verify the addresses match
print(f"\nBoth methods give same address: {derived_addr_1.lower() == derived_addr_2.lower()}")

# Check if the configured wallet has the right format
print(f"\n" + "=" * 80)
print("WALLET FORMAT CHECK")
print("=" * 80)
print(f"Wallet starts with 0x: {wallet.startswith('0x')}")
print(f"Wallet length: {len(wallet)} (should be 42)")
print(f"Wallet is checksum: {wallet == Web3.to_checksum_address(wallet)}")
print(f"Wallet is lowercase: {wallet == wallet.lower()}")

# Check configuration
print(f"\n" + "=" * 80)
print("CONFIGURATION CHECK")
print("=" * 80)
print(f"PORTFOLIO_WALLET_HYPERLIQUID correctly set: {wallet.lower() == derived_addr_1.lower()}")
print(f"PORTFOLIO_WALLET_PRIVATE_KEY correctly set: {Account.from_key(pk_hex).address.lower() == wallet.lower()}")

# Now test signing and recovery
print(f"\n" + "=" * 80)
print("SIGNATURE GENERATION & RECOVERY TEST")
print("=" * 80)

from eth_account.messages import encode_defunct

message = "test message"
message_to_sign = encode_defunct(text=message)

# Sign using account
signed_msg = account.sign_message(message_to_sign)
print(f"\nSigned message:")
print(f"  v: {signed_msg.v}")
print(f"  r: 0x{signed_msg.r.to_bytes(32, byteorder='big').hex()}")
print(f"  s: 0x{signed_msg.s.to_bytes(32, byteorder='big').hex()}")

# Recover address
recovered = Account.recover_message(message_to_sign, signature=signed_msg.signature)
print(f"\nRecovered address: {recovered}")
print(f"Matches original: {recovered.lower() == wallet.lower()}")

print("\n✅ All checks passed! Private key and wallet are valid." if all([
    derived_addr_1.lower() == wallet.lower(),
    derived_addr_2.lower() == wallet.lower(),
    recovered.lower() == wallet.lower()
]) else "\n❌ Some checks failed!")
