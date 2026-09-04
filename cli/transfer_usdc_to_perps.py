#!/usr/bin/env python3
"""
Transfer USDC from Spot to Perpetuals Balance on Hyperliquid

Hyperliquid has TWO USDC balances:
- Spot USDC: NOT usable for margin/trading
- Perpetuals USDC: CAN be used for margin/trading

This script moves USDC from spot → perpetuals using the 3-step flow:
1. Prepare: GET unsigned transfer action
2. Sign: Sign locally with your private key
3. Execute: Submit signed transfer

Usage:
    python cli/transfer_usdc_to_perps.py
"""

import os
import asyncio
import logging
import json
from dotenv import load_dotenv
from eth_account import Account
from eth_account.messages import encode_typed_data

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment
load_dotenv()


async def transfer_usdc_to_perps():
    """Transfer USDC from spot to perpetuals balance"""
    
    # Get credentials
    nansen_api_key = os.getenv("NANSEN_API_KEY")
    wallet_address = os.getenv("PORTFOLIO_WALLET_HYPERLIQUID")
    wallet_private_key = os.getenv("PORTFOLIO_WALLET_PRIVATE_KEY")
    
    if not all([nansen_api_key, wallet_address, wallet_private_key]):
        logger.error("Missing required environment variables:")
        logger.error("  - NANSEN_API_KEY")
        logger.error("  - PORTFOLIO_WALLET_HYPERLIQUID")
        logger.error("  - PORTFOLIO_WALLET_PRIVATE_KEY")
        return False
    
    # Initialize account for signing
    try:
        key = wallet_private_key if wallet_private_key.startswith("0x") else f"0x{wallet_private_key}"
        account = Account.from_key(key)
        logger.info(f"✅ Account loaded: {account.address}")
    except Exception as e:
        logger.error(f"❌ Failed to load account: {e}")
        return False
    
    # Import aiohttp here
    import aiohttp
    
    nansen_base_url = "https://api.nansen.ai/api/v1"
    
    async with aiohttp.ClientSession() as session:
        # Step 0: Check current balance
        logger.info("\n" + "="*70)
        logger.info("STEP 0: Checking current balance...")
        logger.info("="*70)
        
        async with session.get(
            f"{nansen_base_url}/perp/account",
            params={"wallet_address": wallet_address},
            headers={"apikey": nansen_api_key}
        ) as response:
            if response.status != 200:
                logger.error(f"❌ Failed to check balance: HTTP {response.status}")
                return False
            
            balance = await response.json()
            perp_usdc = float(balance.get("balance", 0))
            spot_usdc = float(balance.get("spotUsdc", 0))
            
            logger.info(f"   Perpetuals USDC: ${perp_usdc:,.2f}")
            logger.info(f"   Spot USDC: ${spot_usdc:,.2f}")
        
        if spot_usdc <= 0:
            logger.warning("⚠️  No USDC in spot balance to transfer!")
            return False
        
        # Determine transfer amount
        transfer_amount = spot_usdc  # Transfer all spot USDC to perps
        logger.info(f"\n💰 Will transfer: ${transfer_amount:,.2f}")
        
        # Step 1: PREPARE - Get unsigned transfer action
        logger.info("\n" + "="*70)
        logger.info("STEP 1: Preparing transfer...")
        logger.info("="*70)
        
        prepare_payload = {
            "wallet_address": wallet_address,
            "amount": transfer_amount,
            "to_perp": True  # True = spot → perps, False = perps → spot
        }
        
        logger.info(f"   Request: {prepare_payload}")
        
        async with session.post(
            f"{nansen_base_url}/perp/transfer",
            json=prepare_payload,
            headers={"apikey": nansen_api_key, "Content-Type": "application/json"}
        ) as response:
            if response.status != 200:
                error_msg = await response.text()
                logger.error(f"❌ Prepare failed (HTTP {response.status}): {error_msg}")
                return False
            
            prepare_result = await response.json()
            logger.info(f"✅ Prepare response received")
        
        # Extract unsigned data
        action = prepare_result.get("action")
        nonce = prepare_result.get("nonce")
        eip712_data = prepare_result.get("eip712")
        
        if not all([action, nonce, eip712_data]):
            logger.error("❌ Missing required fields in prepare response")
            logger.error(f"   Response: {prepare_result}")
            return False
        
        logger.info(f"   Action type: {type(action)}")
        logger.info(f"   Nonce: {nonce}")
        logger.info(f"   EIP-712 domain: {eip712_data.get('domain', {}).get('name')}")
        
        # Step 2: SIGN - Sign the EIP-712 message locally
        logger.info("\n" + "="*70)
        logger.info("STEP 2: Signing transfer...")
        logger.info("="*70)
        
        try:
            logger.info(f"   EIP712 domain: {eip712_data.get('domain', {}).get('name')}")
            logger.info(f"   Primary type: {eip712_data.get('primaryType')}")
            
            # Try eth_account's encode_typed_data (works for "Exchange" domain)
            encoded_msg = encode_typed_data(eip712_data)
            
            # Sign with the account
            signed_msg = account.sign_message(encoded_msg)
            
            # Extract signature components (same format as trading)
            signature = {
                "v": signed_msg.v,
                "r": signed_msg.r.to_bytes(32, byteorder='big').hex(),
                "s": signed_msg.s.to_bytes(32, byteorder='big').hex()
            }
            
            # Ensure proper 0x prefixing
            signature["r"] = f"0x{signature['r']}" if not signature["r"].startswith("0x") else signature["r"]
            signature["s"] = f"0x{signature['s']}" if not signature["s"].startswith("0x") else signature["s"]
            
            logger.info(f"✅ Transfer signed successfully (EIP-712 format)")
            logger.info(f"   v: {signature['v']}")
            logger.info(f"   r: {signature['r'][:20]}...")
            logger.info(f"   s: {signature['s'][:20]}...")
            
        except ValueError as e:
            # eth_account rejects this domain type
            logger.warning(f"⚠️  eth_account rejected domain '{eip712_data.get('domain', {}).get('name')}'")
            logger.info("   Trying alternative signing with ECRecovery validation...")
            
            try:
                from eth_account.messages import encode_structured_data
                from eth_keys import keys
                
                # Force encode the data - suppress domain validation temporarily
                # by reconstructing the object
                types_def = {
                    eip712_data["primaryType"]: eip712_data["types"][eip712_data["primaryType"]]
                }
                types_def.update(eip712_data["types"])
                
                # Reconstruct with a workaround
                eip712_modified = {
                    "types": types_def,
                    "primaryType": eip712_data["primaryType"],
                    "domain": eip712_data["domain"],
                    "message": eip712_data["message"]
                }
                
                # Try encoding again
                encoded_msg = encode_structured_data(eip712_modified)
                signed_msg = account.sign_message(encoded_msg)
                
                signature = {
                    "v": signed_msg.v,
                    "r": f"0x{signed_msg.r.to_bytes(32, byteorder='big').hex()}",
                    "s": f"0x{signed_msg.s.to_bytes(32, byteorder='big').hex()}"
                }
                
                logger.info(f"✅ Transfer signed (workaround method)")
                
            except Exception as e2:
                logger.warning(f"   Workaround failed: {e2}")
                logger.info("   Note: HyperliquidSignTransaction domain may require Web3 wallet signing")
                logger.info("   Attempting raw eth_keys signing as fallback...")
                
                try:
                    from eth_keys import keys
                    from web3 import Web3
                    
                    # Let eth_account compute the hash without domain validation
                    # by using its low-level signing
                    msg_json = json.dumps(eip712_data, sort_keys=True)
                    msg_hash = Web3.keccak(text=msg_json)
                    
                    # Use eth_keys for raw signing
                    private_key_bytes = bytes.fromhex(wallet_private_key.replace("0x", ""))
                    pk = keys.PrivateKey(private_key_bytes)
                    sig = pk.sign_msg_hash(msg_hash)
                    
                    signature = {
                        "v": sig.v + 27,
                        "r": f"0x{sig.r.to_bytes(32, byteorder='big').hex()}",
                        "s": f"0x{sig.s.to_bytes(32, byteorder='big').hex()}"
                    }
                    
                    logger.info(f"✅ Transfer signed (raw eth_keys hash)")
                    
                except Exception as e3:
                    logger.error(f"❌ All signing methods exhausted: {e3}", exc_info=True)
                    logger.error("\n💡 SOLUTION: Use the Hyperliquid CLI or Web3 wallet")
                    logger.error("   Command: hyperliquid transfer --amount 219.69 --to-perp")
                    logger.error("   Or: Use browser extension wallet (MetaMask, etc.)")
                    return False
                
        except Exception as e:
            logger.error(f"❌ Unexpected signing error: {e}", exc_info=True)
            return False
        
        # Step 3: EXECUTE - Submit signed transfer
        logger.info("\n" + "="*70)
        logger.info("STEP 3: Executing signed transfer...")
        logger.info("="*70)
        
        execute_payload = {
            "action": action,
            "nonce": nonce,
            "signature": signature
        }
        
        async with session.post(
            f"{nansen_base_url}/perp/execute",
            json=execute_payload,
            headers={"apikey": nansen_api_key, "Content-Type": "application/json"}
        ) as response:
            if response.status != 200:
                error_msg = await response.text()
                logger.error(f"❌ Execute failed (HTTP {response.status}): {error_msg}")
                return False
            
            execute_result = await response.json()
            logger.info(f"✅ Transfer executed successfully!")
            logger.info(f"   Response: {execute_result}")
        
        # Step 4: Verify new balance
        logger.info("\n" + "="*70)
        logger.info("STEP 4: Verifying new balance...")
        logger.info("="*70)
        
        await asyncio.sleep(1)  # Wait 1 second for balance update
        
        async with session.get(
            f"{nansen_base_url}/perp/account",
            params={"wallet_address": wallet_address},
            headers={"apikey": nansen_api_key}
        ) as response:
            if response.status == 200:
                new_balance = await response.json()
                new_perp_usdc = float(new_balance.get("balance", 0))
                new_spot_usdc = float(new_balance.get("spotUsdc", 0))
                
                logger.info(f"   Perpetuals USDC: ${new_perp_usdc:,.2f} (was ${perp_usdc:,.2f})")
                logger.info(f"   Spot USDC: ${new_spot_usdc:,.2f} (was ${spot_usdc:,.2f})")
                
                if new_perp_usdc >= (perp_usdc + transfer_amount - 1):
                    logger.info(f"\n🎉 SUCCESS! Transfer complete!")
                    logger.info(f"   Transferred: ${transfer_amount:,.2f}")
                    logger.info(f"   Now you have ${new_perp_usdc:,.2f} available for trading")
                    return True
                else:
                    logger.warning(f"⚠️  Transfer may not have completed. Balances didn't change as expected.")
                    return False


async def main():
    logger.info("="*70)
    logger.info("HYPERLIQUID: TRANSFER USDC FROM SPOT TO PERPETUALS")
    logger.info("="*70)
    logger.info("\nThis will transfer your spot USDC to perpetuals balance.")
    logger.info("Perpetuals USDC can be used for margin/trading.")
    
    success = await transfer_usdc_to_perps()
    
    if success:
        logger.info("\n" + "="*70)
        logger.info("✅ Transfer successful! You can now trade.")
        logger.info("="*70)
        logger.info("\nNext step:")
        logger.info("  Run: python cli/autonomous_trader.py")
        logger.info("\nThe trading agent will now have sufficient margin to execute trades.")
    else:
        logger.error("\n" + "="*70)
        logger.error("❌ Transfer failed. Check the error messages above.")
        logger.error("="*70)


if __name__ == "__main__":
    asyncio.run(main())
