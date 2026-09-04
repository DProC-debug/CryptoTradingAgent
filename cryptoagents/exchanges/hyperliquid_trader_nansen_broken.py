"""
Hyperliquid Perpetuals Trading Module - via Nansen API
Handles order placement, position management, and trading on Hyperliquid exchange
Uses EIP-712 signing for secure, non-custodial order placement
"""

import asyncio
import logging
from typing import Dict, Optional, List, Tuple
from dataclasses import dataclass, field
from datetime import datetime
import json

import aiohttp
from enum import Enum
from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_keys import keys
from eth_utils import keccak
from hyperliquid import HyperliquidSync

logger = logging.getLogger(__name__)


class OrderType(Enum):
    """Order type enumeration"""
    MARKET = "market"
    LIMIT = "limit"


class PositionSide(Enum):
    """Position side"""
    LONG = "LONG"
    SHORT = "SHORT"


@dataclass
class PositionData:
    """Data class for open positions"""
    position_id: str
    symbol: str
    side: PositionSide
    entry_price: float
    current_price: float
    size: float
    leverage: int
    collateral_used: float
    unrealized_pnl: float
    unrealized_pnl_percentage: float
    entry_time: datetime
    status: str = "open"
    metadata: Dict = field(default_factory=dict)

    @property
    def is_profitable(self) -> bool:
        return self.unrealized_pnl_percentage > 0


@dataclass
class OrderResult:
    """Data class for order execution results"""
    success: bool
    position_id: Optional[str]
    symbol: str
    side: str  # "BUY" or "SELL"
    entry_price: Optional[float]
    size: Optional[float]
    leverage: Optional[int]
    order_id: Optional[str]
    error: Optional[str]
    timestamp: datetime = field(default_factory=datetime.now)
    slippage: float = 0.0


@dataclass
class ClosePositionResult:
    """Data class for position close results"""
    success: bool
    position_id: str
    symbol: str
    exit_price: Optional[float]
    pnl: Optional[float]
    pnl_percentage: Optional[float]
    order_id: Optional[str]
    error: Optional[str]
    timestamp: datetime = field(default_factory=datetime.now)


class HyperliquidTrader:
    """
    Hyperliquid perpetuals trader via Nansen API
    
    Handles:
    - Order placement (market orders for perpetuals)
    - Position management (leverage, sizing)
    - Position closing (take profit, stop loss)
    - Real-time position monitoring
    """
    
    def __init__(self, nansen_api_key: str, wallet_address: str, wallet_private_key: Optional[str] = None, max_leverage: int = 20):
        """
        Initialize Hyperliquid trader
        
        Args:
            nansen_api_key: Nansen API key for authentication
            wallet_address: Wallet address to execute trades from
            wallet_private_key: Private key for signing EIP-712 messages (required for trading)
            max_leverage: Maximum allowed leverage (default 20x)
        """
        self.api_key = nansen_api_key
        self.wallet_address = wallet_address.lower()
        self.wallet_private_key = wallet_private_key
        self.max_leverage = max_leverage
        
        # Initialize account for signing if private key provided
        self.account = None
        if wallet_private_key:
            try:
                # Handle both 0x-prefixed and non-prefixed private keys
                key = wallet_private_key if wallet_private_key.startswith("0x") else f"0x{wallet_private_key}"
                self.account = Account.from_key(key)
                if self.account.address.lower() != self.wallet_address:
                    logger.warning(f"Private key address mismatch!")
                    logger.warning(f"  Expected: {self.wallet_address}")
                    logger.warning(f"  Got: {self.account.address.lower()}")
            except Exception as e:
                logger.error(f"Failed to initialize signing account: {e}")
                self.account = None
        
        # Base URLs
        self.nansen_base_url = "https://api.nansen.ai/api/v1"

        # Official Hyperliquid SDK client (preferred for live order execution)
        self.exchange = None
        if wallet_private_key:
            key = wallet_private_key if wallet_private_key.startswith("0x") else f"0x{wallet_private_key}"
            self.exchange = HyperliquidSync({
                "walletAddress": wallet_address,
                "privateKey": key,
                "options": {
                    "defaultSlippage": 0.05,
                    "sandboxMode": False,
                },
            })
        
        # Session for HTTP requests
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Track open positions
        self.open_positions: Dict[str, PositionData] = {}
        self.closed_trades: List[Dict] = []
        
        logger.info(f"HyperliquidTrader initialized for {wallet_address[:10]}...")
        logger.info(f"  Max Leverage: {max_leverage}x")
        logger.info(f"  Signing enabled: {'Yes' if self.account else 'No - trading disabled'}")
        logger.info(f"  Official SDK enabled: {'Yes' if self.exchange else 'No'}")

    async def __aenter__(self):
        """Context manager entry"""
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        if self.session:
            await self.session.close()

    def _hash_eip712_struct(self, primary_type: str, message: Dict, types: Dict) -> bytes:
        """Hash a typed EIP-712 struct, including Hyperliquid's custom agent payloads."""
        def get_type_string(type_name: str) -> str:
            if type_name not in types:
                return type_name
            fields_data = types[type_name]
            if isinstance(fields_data, list):
                field_strings = [f"{field['type']} {field['name']}" for field in fields_data]
            else:
                field_strings = [f"{field_type} {field_name}" for field_name, field_type in fields_data.items()]
            return f"{type_name}({','.join(field_strings)})"

        type_string = get_type_string(primary_type)
        type_hash = keccak(text=type_string)

        def encode_field(field_name: str, field_type: str, value) -> bytes:
            if field_type == "string":
                return keccak(text=value)
            if field_type == "bytes":
                return keccak(value)
            if field_type.startswith("uint"):
                if isinstance(value, str):
                    value = int(value)
                return value.to_bytes(32, byteorder='big')
            if field_type == "address":
                hex_value = str(value).lower().removeprefix("0x")
                return bytes.fromhex(hex_value.zfill(40))
            if field_type.startswith("bool"):
                return b"\x01" if value else b"\x00"
            if field_type.startswith("bytes"):
                if isinstance(value, str) and value.startswith("0x"):
                    return bytes.fromhex(value[2:])
                if isinstance(value, (bytes, bytearray)):
                    return bytes(value)
                return value.encode() if isinstance(value, str) else bytes(value)
            return self._hash_eip712_struct(field_type, value, types)

        encoded_fields = [type_hash]
        fields_data = types.get(primary_type, [])
        if isinstance(fields_data, list):
            for field in fields_data:
                field_name = field["name"]
                field_type = field["type"]
                encoded_fields.append(encode_field(field_name, field_type, message[field_name]))
        else:
            for field_name, field_type in fields_data.items():
                encoded_fields.append(encode_field(field_name, field_type, message[field_name]))

        return keccak(b"".join(encoded_fields))

    def _sign_eip712_message(self, eip712_data: Dict) -> Optional[Dict]:
        """
        Sign an EIP-712 structured message locally.

        Hyperliquid frequently returns payloads whose `types` do not include an
        explicit `EIP712Domain` entry, which `eth_account` rejects. In that case,
        we rebuild the domain typing and sign the domain+struct digest manually.
        """
        if not self.account:
            logger.error("Cannot sign: private key not configured")
            return None

        try:
            encoded_msg = encode_typed_data(eip712_data)
            signed_msg = self.account.sign_message(encoded_msg)
            signature = {
                "v": signed_msg.v,
                "r": signed_msg.r.to_bytes(32, byteorder='big').hex(),
                "s": signed_msg.s.to_bytes(32, byteorder='big').hex()
            }
            signature["r"] = f"0x{signature['r']}" if not signature["r"].startswith("0x") else signature["r"]
            signature["s"] = f"0x{signature['s']}" if not signature["s"].startswith("0x") else signature["s"]
            logger.debug(f"[OK] Message signed successfully (v={signature['v']})")
            return signature
        except Exception as e:
            logger.warning(f"eth_account signing rejected payload; falling back to raw EIP-712 hashing: {e}")
            try:
                types = dict(eip712_data.get("types", {}))
                domain = eip712_data.get("domain", {})
                primary_type = eip712_data.get("primaryType")
                message = eip712_data.get("message", {})

                domain_types = {
                    "EIP712Domain": [
                        {"name": "chainId", "type": "uint256"},
                        {"name": "name", "type": "string"},
                        {"name": "version", "type": "string"},
                        {"name": "verifyingContract", "type": "address"},
                    ]
                }
                types_with_domain = {**domain_types, **types}

                domain_hash = self._hash_eip712_struct("EIP712Domain", domain, types_with_domain)
                struct_hash = self._hash_eip712_struct(primary_type, message, types_with_domain)
                digest = keccak(b"\x19\x01" + domain_hash + struct_hash)

                private_key_bytes = bytes.fromhex(self.wallet_private_key.lstrip("0x"))
                signed = keys.PrivateKey(private_key_bytes).sign_msg_hash(digest)
                signature = {
                    "v": signed.v,
                    "r": f"0x{signed.r.to_bytes(32, byteorder='big').hex()}",
                    "s": f"0x{signed.s.to_bytes(32, byteorder='big').hex()}"
                }
                logger.debug(f"[OK] Fallback EIP-712 signing succeeded (v={signature['v']})")
                return signature
            except Exception as fallback_error:
                logger.error(f"Fallback signing failed: {fallback_error}", exc_info=True)
                return None

    def _validate_leverage(self, leverage: int) -> int:
        """Validate and cap leverage to maximum"""
        if leverage > self.max_leverage:
            logger.warning(f"Requested leverage {leverage}x exceeds max {self.max_leverage}x, capping")
            return self.max_leverage
        return max(1, leverage)

    async def check_builder_fee_status(self) -> Dict:
        """
        Check builder fee approval status
        
        Returns:
            {
                "approved": bool,
                "max_fee_rate": float,
                "required_fee": int,
                "builder_address": str
            }
        """
        try:
            async with self.session.get(
                f"{self.nansen_base_url}/perp/builder-fee",
                params={"wallet_address": self.wallet_address},
                headers={"apikey": self.api_key}
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    logger.info(f"[OK] Builder fee status checked")
                    logger.info(f"   Approved: {result.get('approved')}")
                    logger.info(f"   Required fee: {result.get('required_fee')}")
                    return result
                else:
                    error = await response.text()
                    logger.error(f"[ERROR] Failed to check builder fee: {error}")
                    return {"approved": False, "error": error}
        except Exception as e:
            logger.error(f"[ERROR] Builder fee check failed: {e}")
            return {"approved": False, "error": str(e)}

    async def get_account_balance(self) -> Dict:
        """
        Get perpetuals account balance and margin info
        
        **UPDATE**: Hyperliquid treats total USDC (spot + perpetuals) as tradeable margin.
        Both balances contribute to available trading margin.
        
        Returns:
            {
                "usdc_balance": float,           # Perpetuals USDC balance
                "spot_usdc_balance": float,      # Spot USDC balance
                "total_usdc": float,             # **Total tradeable USDC (used for margin)**
                "available_margin": float,
                "used_margin": float,
                "liquidation_price": float,
                "error": optional str
            }
        """
        try:
            async with self.session.get(
                f"{self.nansen_base_url}/perp/account",
                params={"wallet_address": self.wallet_address},
                headers={"apikey": self.api_key}
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    
                    if result is None:
                        logger.error(f"[ERROR] Account endpoint returned None")
                        return {"error": "Null response from account endpoint"}
                    
                    # Extract key balances from response structure
                    # Response may have: spotUsdc, marginSummary, crossMarginSummary, etc.
                    spot_balance = float(result.get("spotUsdc", 0))
                    
                    # Perpetuals balance may not be explicitly shown if 0
                    # Look for it in marginSummary.accountValue or use 0
                    margin_summary = result.get("marginSummary", {})
                    perp_balance = float(margin_summary.get("accountValue", 0))
                    
                    total = perp_balance + spot_balance
                    
                    logger.info(f"[OK] Account balance checked")
                    logger.info(f"   Perpetuals USDC: ${perp_balance:,.2f}")
                    logger.info(f"   Spot USDC: ${spot_balance:,.2f}")
                    logger.info(f"   **Total Available for Trading: ${total:,.2f}**")
                    
                    return {
                        "usdc_balance": perp_balance,
                        "spot_usdc_balance": spot_balance,
                        "total_usdc": total,
                        "available_margin": float(margin_summary.get("totalMarginUsed", 0)),
                        "used_margin": float(margin_summary.get("totalMarginUsed", 0)),
                        "liquidation_price": None,
                        "error": None
                    }
                else:
                    error_msg = await response.text()
                    logger.error(f"[ERROR] Failed to get account balance (HTTP {response.status}): {error_msg}")
                    return {"error": error_msg}
        except Exception as e:
            logger.error(f"[ERROR] Failed to get account balance: {e}")
            return {"error": str(e)}

    async def request_approval(self) -> Optional[Dict]:
        """
        Request builder fee approval - returns EIP712 payload for signing
        
        Returns:
            {
                "action": {...},      # EIP712 action to sign
                "eip712": {...},      # Full EIP712 message for signing
                "nonce": int,         # Nonce for this transaction
                "message": "Sign this in MetaMask..."
            }
        """
        try:
            async with self.session.post(
                f"{self.nansen_base_url}/perp/approve-builder-fee",
                json={"wallet_address": self.wallet_address},
                headers={"apikey": self.api_key, "Content-Type": "application/json"}
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    logger.info(f"[OK] Approval request prepared")
                    logger.info(f"   Please sign the EIP712 payload in MetaMask or your signing tool")
                    logger.info(f"   Nonce: {result.get('nonce')}")
                    return result
                else:
                    error = await response.text()
                    logger.error(f"[ERROR] Failed to prepare approval: {error}")
                    return None
        except Exception as e:
            logger.error(f"[ERROR] Approval request failed: {e}")
            return None

    async def execute_approval_with_signature(
        self,
        action: Dict,
        nonce: int,
        signature: Dict
    ) -> bool:
        """
        Execute builder fee approval with locally signed signature
        
        Args:
            action: The action from approval request
            nonce: The nonce from approval request
            signature: {
                "r": "0x...",    # Signature r component
                "s": "0x...",    # Signature s component
                "v": 27 or 28    # Signature v component (recovery id)
            }
            
        Returns:
            True if execution successful, False otherwise
        """
        try:
            payload = {
                "wallet_address": self.wallet_address,
                "action": action,
                "nonce": nonce,
                "signature": signature
            }
            
            async with self.session.post(
                f"{self.nansen_base_url}/perp/execute",
                json=payload,
                headers={"apikey": self.api_key, "Content-Type": "application/json"}
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    logger.info(f"[OK] Builder fee approval executed successfully")
                    logger.info(f"   Transaction hash: {result.get('tx_hash')}")
                    return True
                else:
                    error = await response.text()
                    logger.error(f"[ERROR] Execution failed (HTTP {response.status}): {error}")
                    return False
        except Exception as e:
            logger.error(f"[ERROR] Execution error: {e}")
            return False

    async def ensure_approval(self) -> bool:
        """
        Check if approval is needed and request it
        
        Returns:
            True if already approved or approval requested successfully
        """
        # Check current status
        status = await self.check_builder_fee_status()
        
        if status.get("approved", False):
            logger.info("[OK] Builder fee already approved")
            return True
        
        logger.warning("[WARN] Builder fee approval required")
        logger.info("[INFO] Please complete the following steps:")
        logger.info("  1. Request approval payload...")
        
        # Request approval payload
        approval = await self.request_approval()
        
        if not approval:
            logger.error("[ERROR] Failed to request approval")
            return False
        
        logger.info(f"\n[ACTION REQUIRED] Sign the EIP712 message:")
        logger.info(f"  1. Copy the EIP712 payload below")
        logger.info(f"  2. Sign it in MetaMask (Sign Message)")
        logger.info(f"  3. Provide the signature {{r, s, v}} to the agent")
        logger.info(f"\nEIP712 Payload:")
        logger.info(json.dumps(approval, indent=2))
        
        return False  # Approval process initiated, requires external signing

    async def open_position(
        self,
        symbol: str,
        is_buy: bool,
        size_usd: float,
        leverage: int = 20,
        slippage: float = 0.03,
        price: Optional[float] = None,
        order_type: str = "market"
    ) -> OrderResult:
        """
        Open a perpetual position on Hyperliquid via Nansen API
        
        Uses the prepare-sign-execute flow:
        1. Prepare: Get unsigned action + EIP-712 data
        2. Sign: Sign EIP-712 locally with wallet private key
        3. Execute: Submit signed action to Nansen
        
        Args:
            symbol: Coin symbol (e.g., "BTC", "ETH")
            is_buy: True for long, False for short
            size_usd: Position size in USD (will be converted to asset units)
            leverage: Leverage to use (default 20x, capped at max_leverage)
            slippage: Acceptable slippage (default 0.03 = 3%)
            price: Current market price (required for size conversion)
            order_type: "market" or "limit"
            
        Returns:
            OrderResult with execution details
        """
        
        # Validate prerequisites
        if not self.account:
            logger.error("[ERROR] Trading disabled: wallet private key not configured")
            logger.info("Add PORTFOLIO_WALLET_PRIVATE_KEY to .env to enable trading")
            return OrderResult(
                success=False, position_id=None, symbol=symbol.upper(),
                side="BUY" if is_buy else "SELL", entry_price=None, size=None,
                leverage=None, order_id=None,
                error="Private key not configured"
            )
        
        if not price or price <= 0:
            logger.error(f"[ERROR] Invalid price for {symbol}: {price}")
            return OrderResult(
                success=False, position_id=None, symbol=symbol.upper(),
                side="BUY" if is_buy else "SELL", entry_price=None, size=None,
                leverage=None, order_id=None,
                error="Invalid price for size conversion"
            )
        
        leverage = self._validate_leverage(leverage)

        if self.exchange is not None:
            try:
                market_symbol = f"{symbol.upper()}/USDC:USDC"
                logger.info(f"[SDK] Using official Hyperliquid SDK for {market_symbol}")
                self.exchange.set_leverage(leverage, market_symbol, params={"marginMode": "cross"})
                asset_size = size_usd / price
                order = self.exchange.create_order(
                    market_symbol,
                    "market",
                    "buy" if is_buy else "sell",
                    asset_size,
                    price,
                    params={"slippage": slippage}
                )

                if isinstance(order, dict) and order.get("status") == "ok":
                    response = order.get("response", {})
                    statuses = response.get("data", {}).get("statuses", [])
                    order_id = None
                    if statuses and isinstance(statuses[0], dict):
                        resting = statuses[0].get("resting", {})
                        order_id = resting.get("oid")
                    position_id = f"{symbol.upper()}_{datetime.now().timestamp()}"
                    position = PositionData(
                        position_id=position_id,
                        symbol=symbol.upper(),
                        side=PositionSide.LONG if is_buy else PositionSide.SHORT,
                        entry_price=price,
                        current_price=price,
                        size=size_usd,
                        leverage=leverage,
                        collateral_used=size_usd / leverage,
                        unrealized_pnl=0,
                        unrealized_pnl_percentage=0,
                        entry_time=datetime.now(),
                        metadata={"sdk_order": order}
                    )
                    self.open_positions[position_id] = position
                    return OrderResult(
                        success=True,
                        position_id=position_id,
                        symbol=symbol.upper(),
                        side="BUY" if is_buy else "SELL",
                        entry_price=price,
                        size=size_usd,
                        leverage=leverage,
                        order_id=str(order_id) if order_id is not None else None,
                        error=None,
                        slippage=slippage
                    )
                logger.error(f"[ERROR] Official SDK order failed: {order}")
                return OrderResult(
                    success=False,
                    position_id=None,
                    symbol=symbol.upper(),
                    side="BUY" if is_buy else "SELL",
                    entry_price=None,
                    size=None,
                    leverage=None,
                    order_id=None,
                    error=json.dumps(order, default=str) if isinstance(order, (dict, list)) else str(order)
                )
            except Exception as e:
                logger.error(f"[SDK] Official SDK order execution failed: {e}", exc_info=True)
                return OrderResult(
                    success=False,
                    position_id=None,
                    symbol=symbol.upper(),
                    side="BUY" if is_buy else "SELL",
                    entry_price=None,
                    size=None,
                    leverage=None,
                    order_id=None,
                    error=str(e)
                )
        
        # Check total account balance before trading (spot + perpetuals USDC)
        logger.info(f"[CHECK] Verifying account balance...")
        balance_info = await self.get_account_balance()
        
        if balance_info.get("error"):
            logger.error(f"[ERROR] Failed to check account balance: {balance_info.get('error')}")
            return OrderResult(
                success=False, position_id=None, symbol=symbol.upper(),
                side="BUY" if is_buy else "SELL", entry_price=None, size=None,
                leverage=None, order_id=None,
                error=f"Balance check failed: {balance_info.get('error')}"
            )
        
        total_usdc = balance_info.get("total_usdc", 0)  # Use total available USDC
        required_margin = (size_usd / leverage) * 1.05  # Add 5% buffer for fees
        
        if total_usdc < required_margin:
            logger.error(f"[ERROR] Insufficient margin!")
            logger.error(f"   Required: ${required_margin:.2f}")
            logger.error(f"   Available: ${total_usdc:.2f}")
            logger.error(f"   Breakdown - Perpetuals: ${balance_info.get('usdc_balance', 0):.2f}, Spot: ${balance_info.get('spot_usdc_balance', 0):.2f}")
            return OrderResult(
                success=False, position_id=None, symbol=symbol.upper(),
                side="BUY" if is_buy else "SELL", entry_price=None, size=None,
                leverage=None, order_id=None,
                error=f"Insufficient margin: need ${required_margin:.2f}, have ${total_usdc:.2f} total USDC"
            )
        
        logger.info(f"[OK] Balance check passed")
        logger.info(f"   Using ${required_margin:.2f} of ${total_usdc:.2f} available")
        
        try:
            # Step 1: PREPARE - Get unsigned action + EIP-712 data from Nansen
            logger.info(f"[STEP 1] Preparing order for {symbol}...")
            
            # Convert USD size to asset units using price
            asset_size = size_usd / price
            
            prepare_payload = {
                "wallet_address": self.wallet_address,
                "coin": symbol.upper(),
                "is_buy": is_buy,
                "size": asset_size,  # Size in asset units, not USD
                "price": price,
                "order_type": order_type,
                "slippage": slippage,
                "leverage": leverage
            }
            
            if price and order_type == "limit":
                prepare_payload["price"] = price
            
            # Request prepare data from Nansen
            async with self.session.post(
                f"{self.nansen_base_url}/perp/order",
                json=prepare_payload,
                headers={"apikey": self.api_key, "Content-Type": "application/json"}
            ) as response:
                if response.status != 200:
                    error_msg = await response.text()
                    logger.error(f"[ERROR] Prepare failed (HTTP {response.status}): {error_msg}")
                    return OrderResult(
                        success=False, position_id=None, symbol=symbol.upper(),
                        side="BUY" if is_buy else "SELL", entry_price=None, size=None,
                        leverage=None, order_id=None, error=error_msg
                    )
                
                prepare_result = await response.json()
                logger.debug(f"[OK] Prepare response received")
                
            # Extract unsigned data and EIP-712 message
            action = prepare_result.get("action")
            nonce = prepare_result.get("nonce")
            eip712_data = prepare_result.get("eip712")
            
            # Extract ECHOED size and price (critical - these are what actually gets signed)
            echoed_size = prepare_result.get("size")  # May differ from asset_size due to precision
            echoed_price = prepare_result.get("price")  # For market orders, this is slippage-adjusted
            
            logger.info(f"[PREP] Prepare response echoed values:")
            logger.info(f"   Requested size: {asset_size:.8f} {symbol.upper()}")
            logger.info(f"   Echoed size: {echoed_size} {symbol.upper()} (after precision rounding)")
            logger.info(f"   Requested price: ${price:.2f}")
            logger.info(f"   Echoed price: ${echoed_price} (market order with slippage applied)")
            
            if not all([action, nonce, eip712_data]):
                logger.error("[ERROR] Missing required fields in prepare response")
                return OrderResult(
                    success=False, position_id=None, symbol=symbol.upper(),
                    side="BUY" if is_buy else "SELL", entry_price=None, size=None,
                    leverage=None, order_id=None,
                    error="Incomplete prepare response"
                )
            
            # Step 2: SIGN - Sign the EIP-712 message locally
            logger.info(f"[STEP 2] Signing order...")
            signature = self._sign_eip712_message(eip712_data)
            
            if not signature:
                logger.error("[ERROR] Failed to sign message")
                return OrderResult(
                    success=False, position_id=None, symbol=symbol.upper(),
                    side="BUY" if is_buy else "SELL", entry_price=None, size=None,
                    leverage=None, order_id=None, error="Signing failed"
                )
            
            logger.debug(f"[OK] Message signed")
            
            # Step 3: EXECUTE - Submit signed action to Nansen
            logger.info(f"[STEP 3] Executing signed order...")
            
            execute_payload = {
                "wallet_address": self.wallet_address,
                "action": action,
                "nonce": nonce,
                "signature": signature
            }
            
            async with self.session.post(
                f"{self.nansen_base_url}/perp/execute",
                json=execute_payload,
                headers={"apikey": self.api_key, "Content-Type": "application/json"}
            ) as response:
                if response.status != 200:
                    error_msg = await response.text()
                    logger.error(f"[ERROR] Execute failed (HTTP {response.status}): {error_msg}")
                    return OrderResult(
                        success=False, position_id=None, symbol=symbol.upper(),
                        side="BUY" if is_buy else "SELL", entry_price=None, size=None,
                        leverage=None, order_id=None, error=error_msg
                    )
                
                execute_result = await response.json()
            
            # Log successful order
            position_id = f"{symbol.upper()}_{datetime.now().timestamp()}"
            
            logger.info(f"[SUCCESS] ORDER PLACED: {symbol}")
            logger.info(f"  Direction: {'LONG' if is_buy else 'SHORT'}")
            logger.info(f"  Size: {asset_size:.8f} {symbol.upper()} (${size_usd:.2f})")
            logger.info(f"  Leverage: {leverage}x")
            logger.info(f"  Entry Price: ${price:.2f}")
            logger.info(f"  Collateral: ${size_usd / leverage:.2f}")
            
            # Store position
            position = PositionData(
                position_id=position_id,
                symbol=symbol.upper(),
                side=PositionSide.LONG if is_buy else PositionSide.SHORT,
                entry_price=price,
                current_price=price,
                size=size_usd,  # Store as USD for reference
                leverage=leverage,
                collateral_used=size_usd / leverage,
                unrealized_pnl=0,
                unrealized_pnl_percentage=0,
                entry_time=datetime.now(),
                metadata=execute_result
            )
            self.open_positions[position_id] = position
            
            return OrderResult(
                success=True,
                position_id=position_id,
                symbol=symbol.upper(),
                side="BUY" if is_buy else "SELL",
                entry_price=price,
                size=size_usd,
                leverage=leverage,
                order_id=execute_result.get("order_id"),
                error=None,
                slippage=slippage
            )
            
        except Exception as e:
            logger.error(f"[ERROR] Order execution error: {e}", exc_info=True)
            return OrderResult(
                success=False, position_id=None, symbol=symbol.upper(),
                side="BUY" if is_buy else "SELL", entry_price=None, size=None,
                leverage=None, order_id=None, error=str(e)
            )

    async def close_position(
        self,
        position_id: str,
        slippage: float = 0.03,
        order_type: str = "market"
    ) -> ClosePositionResult:
        """
        Close an open position using prepare-sign-execute flow
        
        Args:
            position_id: Position ID to close
            slippage: Acceptable slippage
            order_type: "market" or "limit"
            
        Returns:
            ClosePositionResult with exit details
        """
        if position_id not in self.open_positions:
            return ClosePositionResult(
                success=False,
                position_id=position_id,
                symbol="UNKNOWN",
                exit_price=None,
                pnl=None,
                pnl_percentage=None,
                order_id=None,
                error="Position not found"
            )
        
        if not self.account:
            logger.error("[ERROR] Cannot close position: wallet private key not configured")
            return ClosePositionResult(
                success=False,
                position_id=position_id,
                symbol="UNKNOWN",
                exit_price=None,
                pnl=None,
                pnl_percentage=None,
                order_id=None,
                error="Private key not configured"
            )
        
        position = self.open_positions[position_id]
        
        try:
            # Step 1: PREPARE - close order
            logger.info(f"[STEP 1] Preparing close order for {position.symbol}...")
            
            # is_buy: false closes a LONG (we sell), true closes a SHORT (we buy to cover)
            prepare_payload = {
                "wallet_address": self.wallet_address,
                "coin": position.symbol,
                "is_buy": position.side == PositionSide.SHORT,  # false for LONG, true for SHORT
                "size": position.size / position.entry_price,  # Convert USD to asset units
                "order_type": order_type,
                "slippage": slippage
            }
            
            async with self.session.post(
                f"{self.nansen_base_url}/perp/close",
                json=prepare_payload,
                headers={"apikey": self.api_key, "Content-Type": "application/json"}
            ) as response:
                if response.status != 200:
                    error_msg = await response.text()
                    logger.error(f"[ERROR] Close prepare failed (HTTP {response.status}): {error_msg}")
                    return ClosePositionResult(
                        success=False,
                        position_id=position_id,
                        symbol=position.symbol,
                        exit_price=None,
                        pnl=None,
                        pnl_percentage=None,
                        order_id=None,
                        error=error_msg
                    )
                
                prepare_result = await response.json()
                logger.debug(f"[OK] Close prepare response received")
            
            # Extract unsigned data
            action = prepare_result.get("action")
            nonce = prepare_result.get("nonce")
            eip712_data = prepare_result.get("eip712")
            
            if not all([action, nonce, eip712_data]):
                logger.error("[ERROR] Missing required fields in close prepare response")
                return ClosePositionResult(
                    success=False,
                    position_id=position_id,
                    symbol=position.symbol,
                    exit_price=None,
                    pnl=None,
                    pnl_percentage=None,
                    order_id=None,
                    error="Incomplete prepare response"
                )
            
            # Step 2: SIGN
            logger.info(f"[STEP 2] Signing close order...")
            signature = self._sign_eip712_message(eip712_data)
            
            if not signature:
                logger.error("[ERROR] Failed to sign close message")
                return ClosePositionResult(
                    success=False,
                    position_id=position_id,
                    symbol=position.symbol,
                    exit_price=None,
                    pnl=None,
                    pnl_percentage=None,
                    order_id=None,
                    error="Signing failed"
                )
            
            # Step 3: EXECUTE
            logger.info(f"[STEP 3] Executing signed close order...")
            
            execute_payload = {
                "wallet_address": self.wallet_address,
                "action": action,
                "nonce": nonce,
                "signature": signature
            }
            
            async with self.session.post(
                f"{self.nansen_base_url}/perp/execute",
                json=execute_payload,
                headers={"apikey": self.api_key, "Content-Type": "application/json"}
            ) as response:
                if response.status != 200:
                    error_msg = await response.text()
                    logger.error(f"[ERROR] Close execute failed (HTTP {response.status}): {error_msg}")
                    return ClosePositionResult(
                        success=False,
                        position_id=position_id,
                        symbol=position.symbol,
                        exit_price=None,
                        pnl=None,
                        pnl_percentage=None,
                        order_id=None,
                        error=error_msg
                    )
                
                execute_result = await response.json()
            
            # Calculate exit details
            exit_price = execute_result.get("exit_price", position.current_price)
            
            # Calculate P&L
            if position.side == PositionSide.LONG:
                pnl = (exit_price - position.entry_price) * position.size / position.entry_price
            else:
                pnl = (position.entry_price - exit_price) * position.size / position.entry_price
            
            pnl_percentage = pnl / (position.collateral_used) if position.collateral_used > 0 else 0
            
            logger.info(f"[SUCCESS] POSITION CLOSED: {position.symbol}")
            logger.info(f"  Exit Price: ${exit_price:.2f}")
            logger.info(f"  Entry Price: ${position.entry_price:.2f}")
            logger.info(f"  P&L: ${pnl:.2f} ({pnl_percentage*100:.2f}%)")
            
            # Move to closed trades
            trade_record = {
                "position_id": position_id,
                "symbol": position.symbol,
                "side": position.side.value,
                "entry_price": position.entry_price,
                "exit_price": exit_price,
                "size": position.size,
                "leverage": position.leverage,
                "pnl": pnl,
                "pnl_percentage": pnl_percentage,
                "entry_time": position.entry_time.isoformat(),
                "exit_time": datetime.now().isoformat(),
                "duration_minutes": (datetime.now() - position.entry_time).total_seconds() / 60
            }
            self.closed_trades.append(trade_record)
            
            # Remove from open positions
            del self.open_positions[position_id]
            
            return ClosePositionResult(
                success=True,
                position_id=position_id,
                symbol=position.symbol,
                exit_price=exit_price,
                pnl=pnl,
                pnl_percentage=pnl_percentage,
                order_id=execute_result.get("order_id"),
                error=None
            )
                    
        except Exception as e:
            logger.error(f"[ERROR] Close position error: {e}", exc_info=True)
            return ClosePositionResult(
                success=False,
                position_id=position_id,
                symbol=position.symbol,
                exit_price=None,
                pnl=None,
                pnl_percentage=None,
                order_id=None,
                error=str(e)
            )

    async def get_open_positions(self) -> List[PositionData]:
        """Get all open positions"""
        return list(self.open_positions.values())

    async def get_position(self, position_id: str) -> Optional[PositionData]:
        """Get specific position by ID"""
        return self.open_positions.get(position_id)

    async def update_positions(self, current_prices: Dict[str, float]) -> None:
        """
        Update open positions with current market prices
        
        Args:
            current_prices: Dict of {symbol: current_price}
        """
        for position_id, position in self.open_positions.items():
            if position.symbol in current_prices:
                current_price = current_prices[position.symbol]
                position.current_price = current_price
                
                # Calculate unrealized PnL
                if position.side == PositionSide.LONG:
                    pnl = (current_price - position.entry_price) * position.size / position.entry_price
                else:
                    pnl = (position.entry_price - current_price) * position.size / position.entry_price
                
                position.unrealized_pnl = pnl
                position.unrealized_pnl_percentage = pnl / position.collateral_used if position.collateral_used > 0 else 0

    async def monitor_positions_for_close(
        self,
        take_profit_pct: float = 0.30,
        stop_loss_pct: float = -0.30
    ) -> List[Tuple[str, str]]:  # List of (position_id, reason)
        """
        Check all positions for take-profit or stop-loss conditions
        
        Args:
            take_profit_pct: Profit target (e.g., 0.30 = 30%)
            stop_loss_pct: Loss limit (e.g., -0.30 = -30%)
            
        Returns:
            List of (position_id, close_reason) tuples
        """
        positions_to_close = []
        
        for position_id, position in list(self.open_positions.items()):
            pnl_pct = position.unrealized_pnl_percentage
            
            if pnl_pct >= take_profit_pct:
                positions_to_close.append((position_id, f"TAKE_PROFIT_{pnl_pct*100:.2f}%"))
            elif pnl_pct <= stop_loss_pct:
                positions_to_close.append((position_id, f"STOP_LOSS_{pnl_pct*100:.2f}%"))
        
        return positions_to_close

    def get_trade_statistics(self) -> Dict:
        """Get statistics on closed trades"""
        if not self.closed_trades:
            return {
                "total_trades": 0,
                "winning_trades": 0,
                "losing_trades": 0,
                "win_rate": 0,
                "total_pnl": 0,
                "avg_profit": 0,
                "avg_loss": 0
            }
        
        winning = [t for t in self.closed_trades if t["pnl"] > 0]
        losing = [t for t in self.closed_trades if t["pnl"] < 0]
        
        total_pnl = sum(t["pnl"] for t in self.closed_trades)
        avg_profit = sum(t["pnl"] for t in winning) / len(winning) if winning else 0
        avg_loss = sum(t["pnl"] for t in losing) / len(losing) if losing else 0
        
        return {
            "total_trades": len(self.closed_trades),
            "winning_trades": len(winning),
            "losing_trades": len(losing),
            "win_rate": len(winning) / len(self.closed_trades) if self.closed_trades else 0,
            "total_pnl": total_pnl,
            "avg_profit": avg_profit,
            "avg_loss": avg_loss,
            "profit_factor": abs(sum(t["pnl"] for t in winning) / sum(t["pnl"] for t in losing)) if losing else 0
        }

    def get_portfolio_state(self) -> Dict:
        """Get current portfolio state"""
        total_collateral = sum(p.collateral_used for p in self.open_positions.values())
        total_unrealized_pnl = sum(p.unrealized_pnl for p in self.open_positions.values())
        
        return {
            "open_positions": len(self.open_positions),
            "total_collateral_used": total_collateral,
            "total_unrealized_pnl": total_unrealized_pnl,
            "positions": [
                {
                    "symbol": p.symbol,
                    "side": p.side.value,
                    "entry_price": p.entry_price,
                    "current_price": p.current_price,
                    "size": p.size,
                    "leverage": p.leverage,
                    "pnl": p.unrealized_pnl,
                    "pnl_pct": f"{p.unrealized_pnl_percentage*100:.2f}%"
                }
                for p in self.open_positions.values()
            ]
        }
