"""
Hyperliquid Perpetuals Trading Module - Official SDK
Handles order placement, position management, and trading on Hyperliquid exchange
Uses official hyperliquid-python-sdk for secure, efficient order placement
"""

import logging
from typing import Dict, Optional, List
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import time

from hyperliquid.exchange import Exchange
from hyperliquid.utils.constants import MAINNET_API_URL
from eth_account import Account

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
    Hyperliquid perpetuals trader using official SDK
    
    Handles:
    - Order placement (market orders for perpetuals)
    - Position management (leverage, sizing)
    - Position closing (take profit, stop loss)
    - Real-time position monitoring
    
    NOTE: All methods are SYNCHRONOUS (official SDK is sync-only)
    """
    
    # Asset-specific precision (szDecimals - decimals for order size)
    ASSET_PRECISION = {
        "BTC": 4,   # 0.0001 BTC minimum
        "ETH": 3,   # 0.001 ETH minimum
        "SOL": 2,   # 0.01 SOL minimum
        "ARB": 1,   # 0.1 ARB minimum
        "OP": 1,    # 0.1 OP minimum
    }
    
    def __init__(self, wallet_address: str, wallet_private_key: str, max_leverage: int = 20):
        """
        Initialize Hyperliquid trader with official SDK
        
        Args:
            wallet_address: User's Hyperliquid wallet address
            wallet_private_key: Private key for signing transactions
            max_leverage: Maximum leverage for positions (default 20x)
        """
        self.wallet_address = wallet_address
        self.wallet_private_key = wallet_private_key
        self.max_leverage = max_leverage
        
        # Initialize account from private key
        try:
            account = Account.from_key(
                wallet_private_key if wallet_private_key.startswith("0x") 
                else f"0x{wallet_private_key}"
            )
            self.exchange = Exchange(account, base_url=MAINNET_API_URL)
            logger.info(f"✅ HyperliquidTrader initialized for {account.address}")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Hyperliquid SDK: {e}")
            raise

    def get_account_balance(self) -> Dict:
        """
        Retrieve current account balance and position summary
        
        Returns:
            Dict with account balance, collateral, positions summary
        """
        try:
            # Get user clearing house state via API
            user_state = self.exchange.post("/info", {
                "type": "clearinghouseState", 
                "user": self.wallet_address
            })
            
            if not user_state:
                logger.error("Failed to get user state")
                return {"error": "No user state returned", "total_collateral": 0}
            
            # Extract cross margin info
            margin_summary = user_state.get("marginSummary", {})
            
            account_info = {
                "total_collateral": float(margin_summary.get("accountValue", 0)),
                "cross_margin": float(margin_summary.get("crossMarginUsed", 0)),
                "free_collateral": float(margin_summary.get("accountValue", 0)) - float(margin_summary.get("crossMarginUsed", 0)),
                "open_positions": len([p for p in user_state.get("assetPositions", []) if float(p.get("szi", 0)) != 0]),
                "timestamp": datetime.now().isoformat()
            }
            
            logger.info(f"Account balance: ${account_info['total_collateral']:.2f}")
            return account_info
            
        except Exception as e:
            logger.error(f"❌ Failed to get account balance: {e}")
            return {"error": str(e), "total_collateral": 0}

    def _round_size(self, symbol: str, size: float) -> float:
        """
        Round order size to asset's precision requirements
        
        Args:
            symbol: Asset symbol (e.g., 'BTC', 'ETH')
            size: Order size in units of asset
            
        Returns:
            Rounded size matching asset's szDecimals
        """
        decimals = self.ASSET_PRECISION.get(symbol, 1)
        divisor = 10 ** decimals
        return round(size * divisor) / divisor

    def open_position(
        self,
        symbol: str,
        is_buy: bool,
        size_usd: float,
        price: float,
        leverage: float = 1.0,
        slippage: float = 0.03,
        order_type: str = "market"
    ) -> OrderResult:
        """
        Open a new perpetual position on Hyperliquid
        
        Args:
            symbol: Asset to trade (e.g., 'BTC', 'ETH')
            is_buy: True for long, False for short
            size_usd: Position size in USD
            price: Current market price
            leverage: Leverage multiplier (default 1x)
            slippage: Slippage tolerance (default 3%)
            order_type: 'market' or 'limit' (default 'market')
            
        Returns:
            OrderResult with execution status and details
        """
        try:
            # Calculate order size in asset units
            asset_size = size_usd / price
            asset_size = self._round_size(symbol, asset_size)
            
            logger.info(f"📍 Opening {symbol} position: {asset_size} units @ ${price}")
            
            # Prepare limit price (with slippage adjustment)
            limit_px = price * (1 - slippage if is_buy else 1 + slippage)
            
            # For market orders in Hyperliquid SDK, use IOC (Immediate or Cancel) limit order
            order_type_obj = {"limit": {"tif": "Ioc"}}
            
            # Place order using official SDK
            # The order() method signature: order(name, is_buy, sz, limit_px, order_type, reduce_only, cloid, builder)
            order_result = self.exchange.order(
                name=symbol,
                is_buy=is_buy,
                sz=asset_size,
                limit_px=limit_px,
                order_type=order_type_obj,
                reduce_only=False
            )
            
            logger.info(f"✅ Order result: {order_result}")
            
            # Parse response
            # The SDK returns a dictionary with the order response
            if isinstance(order_result, dict):
                status = order_result.get("status")
                if status == "ok":
                    order_id = order_result.get("response", {}).get("data", {}).get("orderId", "")
                    return OrderResult(
                        success=True,
                        position_id=order_id,
                        symbol=symbol,
                        side="BUY" if is_buy else "SELL",
                        entry_price=price,
                        size=asset_size,
                        leverage=int(leverage),
                        order_id=order_id,
                        error=None,
                        slippage=slippage
                    )
                else:
                    error_msg = order_result.get("response", {}).get("data", {}).get("error", "Unknown error") or str(order_result)
                    logger.error(f"❌ Order execution failed: {error_msg}")
                    return OrderResult(
                        success=False,
                        position_id=None,
                        symbol=symbol,
                        side="BUY" if is_buy else "SELL",
                        entry_price=None,
                        size=asset_size,
                        leverage=int(leverage),
                        order_id=None,
                        error=f"Order failed: {error_msg}"
                    )
            else:
                # Response might be direct result or wrapped differently
                logger.info(f"Response type: {type(order_result)} - {order_result}")
                return OrderResult(
                    success=True,
                    position_id=str(order_result),
                    symbol=symbol,
                    side="BUY" if is_buy else "SELL",
                    entry_price=price,
                    size=asset_size,
                    leverage=int(leverage),
                    order_id=None,
                    error=None,
                    slippage=slippage
                )
                
        except Exception as e:
            logger.error(f"❌ Failed to open position: {e}")
            import traceback
            traceback.print_exc()
            return OrderResult(
                success=False,
                position_id=None,
                symbol=symbol,
                side="BUY" if is_buy else "SELL",
                entry_price=None,
                size=0,
                leverage=int(leverage),
                order_id=None,
                error=str(e)
            )

    def close_position(
        self,
        symbol: str,
        position_size: float,
        current_price: float,
        slippage: float = 0.03
    ) -> ClosePositionResult:
        """
        Close an existing perpetual position
        
        Args:
            symbol: Asset to close position for
            position_size: Current position size in units
            current_price: Current market price
            slippage: Slippage tolerance
            
        Returns:
            ClosePositionResult with execution status
        """
        try:
            logger.info(f"📍 Closing {symbol} position: {position_size} units @ ${current_price}")
            
            # Close by going opposite direction
            is_buy = position_size < 0  # If position is short, buy to close
            close_size = abs(position_size)
            close_size = self._round_size(symbol, close_size)
            
            # Slippage adjustment for close
            limit_px = current_price * (1 + slippage if is_buy else 1 - slippage)
            
            # Place close order using IOC
            order_result = self.exchange.order(
                name=symbol,
                is_buy=is_buy,
                sz=close_size,
                limit_px=limit_px,
                order_type={"limit": {"tif": "Ioc"}},
                reduce_only=True  # Close only, don't reverse
            )
            
            logger.info(f"✅ Close order result: {order_result}")
            
            if isinstance(order_result, dict) and order_result.get("status") == "ok":
                order_id = order_result.get("response", {}).get("data", {}).get("orderId")
                return ClosePositionResult(
                    success=True,
                    position_id=symbol,
                    symbol=symbol,
                    exit_price=current_price,
                    pnl=None,  # Would need to calculate from order fills
                    pnl_percentage=None,
                    order_id=order_id,
                    error=None
                )
            else:
                error_msg = order_result.get("response", {}).get("data", {}).get("error", "Unknown error") if isinstance(order_result, dict) else str(order_result)
                return ClosePositionResult(
                    success=False,
                    position_id=symbol,
                    symbol=symbol,
                    exit_price=None,
                    pnl=None,
                    pnl_percentage=None,
                    order_id=None,
                    error=f"Close failed: {error_msg}"
                )
                
        except Exception as e:
            logger.error(f"❌ Failed to close position: {e}")
            return ClosePositionResult(
                success=False,
                position_id=symbol,
                symbol=symbol,
                exit_price=None,
                pnl=None,
                pnl_percentage=None,
                order_id=None,
                error=str(e)
            )

    def get_open_positions(self) -> List[PositionData]:
        """
        Get list of all open positions
        
        Returns:
            List of PositionData objects for open positions
        """
        try:
            user_state = self.exchange.post("/info", {
                "type": "clearinghouseState",
                "user": self.wallet_address
            })
            if not user_state:
                logger.warning("No user state returned")
                return []
            
            positions_raw = user_state.get("assetPositions", [])
            
            open_positions = []
            for entry in positions_raw:
                pos = entry.get("position", entry)  # unwrap {"type": "oneWay", "position": {...}}
                szi = float(pos.get("szi", 0))
                if szi == 0:
                    continue  # Skip closed positions
                
                coin = pos.get("coin", "")
                
                entry_px = float(pos.get("entryPx", 0)) if pos.get("entryPx") else 0
                mark_px = float(pos.get("markPx", 0)) if pos.get("markPx") else 0
                leverage_field = pos.get("leverage", 1)
                leverage = int(leverage_field.get("value", 1)) if isinstance(leverage_field, dict) else int(float(leverage_field or 1))
                margin_used = float(pos.get("marginUsed", 0) or 0)
                unrealized_pnl = float(pos.get("unrealizedPnl", 0))

                # Prefer Hyperliquid's own returnOnEquity (return on margin) - pnl/notional
                # understates real P&L% by roughly `leverage`x and would make TP/SL never fire.
                if pos.get("returnOnEquity") is not None:
                    pnl_pct = float(pos["returnOnEquity"]) * 100
                elif margin_used:
                    pnl_pct = (unrealized_pnl / margin_used) * 100
                else:
                    pnl_pct = 0

                position_data = PositionData(
                    position_id=f"{coin}_{szi}",
                    symbol=coin,
                    side=PositionSide.LONG if szi > 0 else PositionSide.SHORT,
                    entry_price=entry_px,
                    current_price=mark_px,
                    size=abs(szi),
                    leverage=leverage,
                    collateral_used=margin_used if margin_used else (abs(szi) * mark_px / leverage if mark_px and leverage else 0),
                    unrealized_pnl=unrealized_pnl,
                    unrealized_pnl_percentage=pnl_pct,
                    entry_time=datetime.now(),  # Would need from position details
                    status="open"
                )
                open_positions.append(position_data)
            
            logger.info(f"Found {len(open_positions)} open positions")
            return open_positions
            
        except Exception as e:
            logger.error(f"❌ Failed to get open positions: {e}")
            return []
