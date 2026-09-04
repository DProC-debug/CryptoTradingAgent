"""
Hyperliquid Perpetuals Trading via Nansen API
Routes all trading through Nansen's prepare -> sign -> execute flow (docs.nansen.ai/api/trade/perp-trading)
Keys never leave this process: Nansen returns unsigned EIP-712 typed data, we sign locally, we submit the signature.
"""

import logging
from typing import Dict, Optional, List
from datetime import datetime

import requests
from eth_account import Account
from eth_account.messages import encode_typed_data

from cryptoagents.exchanges.hyperliquid_trader import (
    OrderResult,
    ClosePositionResult,
    PositionData,
    PositionSide,
)

logger = logging.getLogger(__name__)


class NansenPerpTrader:
    """
    Hyperliquid perpetuals trader routed through Nansen's Perpetual Trading API.

    Every state change (order, close, cancel, leverage, transfer, builder-fee approval)
    follows the same flow:
        1. Prepare  - POST the intent, get back an unsigned `action` + `nonce` + `eip712`
        2. Sign     - sign the `eip712` payload locally with the wallet's key
        3. Execute  - POST `action` + `nonce` + `signature` to /perp/execute

    NOTE: `action`/`nonce` must be forwarded byte-for-byte as received from prepare -
    do not recompute, round, or re-derive them before executing.
    """

    BASE_URL = "https://api.nansen.ai/api/v1"

    # Asset-specific precision (szDecimals - decimals for order size), same as HyperliquidTrader
    ASSET_PRECISION = {
        "BTC": 4,
        "ETH": 3,
        "SOL": 2,
        "ARB": 1,
        "OP": 1,
    }

    def __init__(self, api_key: str, wallet_address: str, wallet_private_key: str, max_leverage: int = 20):
        """
        Args:
            api_key: Nansen API key
            wallet_address: The wallet being traded (0x...)
            wallet_private_key: Private key used to sign EIP-712 actions locally
            max_leverage: Maximum leverage cap for position sizing
        """
        if not api_key:
            raise ValueError("NANSEN_API_KEY not set")
        if not wallet_address:
            raise ValueError("wallet_address is required")
        if not wallet_private_key:
            raise ValueError("wallet_private_key is required")

        self.api_key = api_key
        self.wallet_address = wallet_address
        self.max_leverage = max_leverage
        self.account = Account.from_key(
            wallet_private_key if wallet_private_key.startswith("0x") else f"0x{wallet_private_key}"
        )

        self.session = requests.Session()
        self.session.headers.update({
            "apikey": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

        logger.info(f"NansenPerpTrader initialized for {self.account.address}")

    # ------------------------------------------------------------------
    # Core prepare -> sign -> execute plumbing
    # ------------------------------------------------------------------

    def _sign_eip712(self, eip712_data: Dict) -> Dict:
        """Sign a Nansen-provided EIP-712 typed-data payload with the wallet's key.

        `eip712_data` already contains domain/types/primaryType/message - it must be
        passed to eth_account as `full_message`, not positionally, or the domain is
        misinterpreted and the signature will never recover to the right address.
        """
        encoded = encode_typed_data(full_message=eip712_data)
        signed = self.account.sign_message(encoded)
        return {
            "r": f"0x{signed.r.to_bytes(32, byteorder='big').hex()}",
            "s": f"0x{signed.s.to_bytes(32, byteorder='big').hex()}",
            "v": signed.v,
        }

    def _prepare(self, endpoint: str, payload: dict) -> dict:
        """POST to a /perp/<endpoint> prepare route. Returns the raw JSON response."""
        url = f"{self.BASE_URL}/perp/{endpoint}"
        response = self.session.post(url, json=payload, timeout=30)
        if response.status_code != 200:
            raise RuntimeError(f"Prepare {endpoint} failed (HTTP {response.status_code}): {response.text}")
        return response.json()

    def _execute(self, action: dict, nonce: int, signature: dict, vault_address: Optional[str] = None) -> dict:
        """POST the signed action to /perp/execute. A 2xx here means the exchange really accepted it."""
        payload = {
            "wallet_address": self.wallet_address,
            "action": action,
            "nonce": nonce,
            "signature": signature,
        }
        if vault_address:
            payload["vault_address"] = vault_address

        url = f"{self.BASE_URL}/perp/execute"
        response = self.session.post(url, json=payload, timeout=30)
        if response.status_code != 200:
            raise RuntimeError(f"Execute failed (HTTP {response.status_code}): {response.text}")
        return response.json()

    def _prepare_sign_execute(self, endpoint: str, payload: dict) -> dict:
        """Run the full prepare -> sign -> execute cycle for one action."""
        prepared = self._prepare(endpoint, payload)

        action = prepared.get("action")
        nonce = prepared.get("nonce")
        eip712_data = prepared.get("eip712")
        if not all([action, nonce, eip712_data]):
            raise RuntimeError(f"Incomplete prepare response for {endpoint}: {prepared}")

        signature = self._sign_eip712(eip712_data)
        result = self._execute(action, nonce, signature, prepared.get("vault_address"))
        result["_prepared"] = prepared  # keep echoed size/price available to callers
        return result

    # ------------------------------------------------------------------
    # Builder fee (one-time, wallet's own key only)
    # ------------------------------------------------------------------

    def get_builder_fee_status(self) -> dict:
        """GET /perp/builder-fee - read-only, no signing"""
        response = self.session.get(
            f"{self.BASE_URL}/perp/builder-fee",
            params={"wallet_address": self.wallet_address},
            timeout=15,
        )
        response.raise_for_status()
        return response.json()

    def approve_builder_fee(self) -> dict:
        """Prepare + sign + execute the one-time builder-fee approval. Must be signed by the wallet's own key."""
        logger.info(f"Approving Nansen builder fee for {self.wallet_address}")
        return self._prepare_sign_execute("approve-builder-fee", {"wallet_address": self.wallet_address})

    # ------------------------------------------------------------------
    # Spot <-> Perps USDC transfer (wallet's own key only)
    # ------------------------------------------------------------------

    def prepare_transfer(self, amount: float, to_perp: bool) -> dict:
        """Prepare (only) a spot<->perps USDC transfer - no signing, no execution, nothing moves yet.

        Safe to call freely to validate the request shape/amount before ever signing.

        Args:
            amount: USDC amount to move
            to_perp: True moves spot -> perps, False moves perps -> spot
        """
        payload = {
            "wallet_address": self.wallet_address,
            "amount": amount,
            "to_perp": to_perp,
        }
        return self._prepare("transfer", payload)

    def transfer(self, amount: float, to_perp: bool) -> dict:
        """Prepare + sign + execute a spot<->perps USDC transfer. Moves real funds. Signed by the wallet's own key.

        Args:
            amount: USDC amount to move
            to_perp: True moves spot -> perps, False moves perps -> spot
        """
        direction = "spot -> perps" if to_perp else "perps -> spot"
        logger.info(f"Transferring ${amount} USDC ({direction}) for {self.wallet_address}")
        return self._prepare_sign_execute("transfer", {
            "wallet_address": self.wallet_address,
            "amount": amount,
            "to_perp": to_perp,
        })

    def transfer_to_perps(self, amount: float) -> dict:
        """Move USDC from spot into the perps margin balance (usable for trading)."""
        return self.transfer(amount, to_perp=True)

    def transfer_to_spot(self, amount: float) -> dict:
        """Move USDC from perps margin back into spot."""
        return self.transfer(amount, to_perp=False)

    # ------------------------------------------------------------------
    # Leverage (per asset, applies to positions opened afterwards)
    # ------------------------------------------------------------------

    def prepare_leverage(self, symbol: str, leverage: int, is_cross: bool = False) -> dict:
        """Prepare (only) a leverage change - no signing, no execution, nothing changes yet."""
        payload = {
            "wallet_address": self.wallet_address,
            "coin": symbol.upper(),
            "leverage": leverage,
            "is_cross": is_cross,
        }
        return self._prepare("leverage", payload)

    def set_leverage(self, symbol: str, leverage: int, is_cross: bool = False) -> dict:
        """Prepare + sign + execute a leverage change for one asset.

        Applies only to positions opened after this call - does not re-margin an existing position.
        """
        mode = "cross" if is_cross else "isolated"
        logger.info(f"Setting {symbol.upper()} leverage to {leverage}x ({mode})")
        return self._prepare_sign_execute("leverage", {
            "wallet_address": self.wallet_address,
            "coin": symbol.upper(),
            "leverage": leverage,
            "is_cross": is_cross,
        })

    # ------------------------------------------------------------------
    # Read-only account/position state
    # ------------------------------------------------------------------

    def get_account_balance(self) -> Dict:
        """GET /perp/account, mapped to the same shape HyperliquidTrader.get_account_balance() returns.

        This account runs in Hyperliquid's "Unified Account" mode, where `spotUsdc` is the gross
        total balance (it does NOT shrink as isolated margin gets committed to open positions -
        confirmed empirically, and manual spot<->perps transfers are outright rejected by the API
        with "Action disabled when unified account is active"). So the real usable-for-new-trades
        amount is `spotUsdc` minus whatever margin is already locked in open positions, not the
        `marginSummary`/`withdrawable` fields, which only reflect the isolated-margin sub-ledger.
        """
        try:
            response = self.session.get(
                f"{self.BASE_URL}/perp/account",
                params={"wallet_address": self.wallet_address},
                timeout=15,
            )
            response.raise_for_status()
            data = response.json()

            spot_usdc = float(data.get("spotUsdc", 0) or 0)
            asset_positions = data.get("assetPositions", [])
            margin_used = sum(
                float(entry.get("position", entry).get("marginUsed", 0) or 0)
                for entry in asset_positions
            )
            total_collateral = spot_usdc
            free_collateral = max(0.0, spot_usdc - margin_used)

            return {
                "total_collateral": total_collateral,
                "free_collateral": free_collateral,
                "spot_usdc": spot_usdc,
                "open_positions": len(asset_positions),
                "raw": data,
            }
        except Exception as e:
            logger.error(f"Failed to fetch Nansen perp account state: {e}")
            return {"error": str(e)}

    def get_open_positions(self) -> List[PositionData]:
        """GET /perp/positions, mapped to PositionData objects (same shape as HyperliquidTrader).

        Hyperliquid wraps each entry as `{"type": "oneWay", "position": {...fields...}}`
        (mirrors the raw clearinghouseState shape) - fields must be read from the nested
        `position` object, not the wrapper itself.
        """
        try:
            response = self.session.get(
                f"{self.BASE_URL}/perp/positions",
                params={"wallet_address": self.wallet_address},
                timeout=15,
            )
            response.raise_for_status()
            body = response.json()
            positions_raw = body.get("positions", body if isinstance(body, list) else [])

            open_positions = []
            for entry in positions_raw:
                pos = entry.get("position", entry)  # unwrap {"type": ..., "position": {...}}

                size = float(pos.get("size", pos.get("szi", 0)) or 0)
                if size == 0:
                    continue

                entry_price = float(pos.get("entryPrice", pos.get("entryPx", 0)) or 0)
                current_price = float(pos.get("markPrice", pos.get("markPx", entry_price)) or 0)
                leverage_field = pos.get("leverage", 1)
                leverage = int(leverage_field.get("value", 1)) if isinstance(leverage_field, dict) else int(float(leverage_field or 1))
                margin_used = float(pos.get("marginUsed", 0) or 0)
                unrealized_pnl = float(pos.get("unrealizedPnl", 0) or 0)

                # Prefer Hyperliquid's own returnOnEquity (return on margin) - pnl/notional
                # understates real P&L% by roughly `leverage`x and would make TP/SL never fire.
                if pos.get("returnOnEquity") is not None:
                    pnl_pct = float(pos["returnOnEquity"]) * 100
                elif margin_used:
                    pnl_pct = (unrealized_pnl / margin_used) * 100
                else:
                    pnl_pct = 0

                open_positions.append(PositionData(
                    position_id=f"{pos.get('coin', '')}_{size}",
                    symbol=pos.get("coin", pos.get("symbol", "")),
                    side=PositionSide.LONG if size > 0 else PositionSide.SHORT,
                    entry_price=entry_price,
                    current_price=current_price,
                    size=abs(size),
                    leverage=leverage,
                    collateral_used=margin_used if margin_used else (abs(size) * current_price / leverage if leverage and current_price else 0),
                    unrealized_pnl=unrealized_pnl,
                    unrealized_pnl_percentage=pnl_pct,
                    entry_time=datetime.now(),
                    status="open",
                ))

            return open_positions
        except Exception as e:
            logger.error(f"Failed to fetch Nansen perp positions: {e}")
            return []

    # ------------------------------------------------------------------
    # Trading actions (real money - prepare/sign/execute)
    # ------------------------------------------------------------------

    def open_position(
        self,
        symbol: str,
        is_buy: bool,
        size_usd: float,
        price: float,
        leverage: float = 1.0,
        slippage: float = 0.03,
        order_type: str = "market",
    ) -> OrderResult:
        """Open a position via POST /perp/order (prepare) -> sign -> /perp/execute."""
        try:
            asset_size = round(size_usd / price, self.ASSET_PRECISION.get(symbol.upper(), 4))

            payload = {
                "wallet_address": self.wallet_address,
                "coin": symbol.upper(),
                "is_buy": is_buy,
                "size": asset_size,
                "price": price,
                "order_type": order_type,
                "slippage": slippage,
            }

            result = self._prepare_sign_execute("order", payload)
            prepared = result["_prepared"]
            echoed_price = prepared.get("price") or price
            echoed_size = prepared.get("size") or asset_size

            logger.info(f"[SUCCESS] Nansen order placed: {symbol} {'BUY' if is_buy else 'SELL'} {echoed_size} @ ${echoed_price}")

            return OrderResult(
                success=True,
                position_id=f"{symbol.upper()}_{datetime.now().timestamp()}",
                symbol=symbol.upper(),
                side="BUY" if is_buy else "SELL",
                entry_price=float(echoed_price),
                size=float(echoed_size),
                leverage=int(leverage),
                order_id=result.get("orderId"),
                error=None,
                slippage=slippage,
            )
        except Exception as e:
            logger.error(f"Failed to open position via Nansen for {symbol}: {e}")
            return OrderResult(
                success=False,
                position_id=None,
                symbol=symbol.upper(),
                side="BUY" if is_buy else "SELL",
                entry_price=None,
                size=None,
                leverage=int(leverage),
                order_id=None,
                error=str(e),
            )

    def close_position(
        self,
        symbol: str,
        position_size: float,
        current_price: float,
        slippage: float = 0.03,
    ) -> ClosePositionResult:
        """Close a position via POST /perp/close (prepare) -> sign -> /perp/execute.

        `is_buy` is the opposite of the position's direction (buy to close a short, sell to close a long).
        """
        try:
            is_buy = position_size < 0
            close_size = abs(position_size)

            # /perp/close has no "slippage" field like /perp/order does - apply the buffer to
            # the price ourselves so the aggressive close order actually crosses the book instead
            # of sitting unmatched at the exact last-seen price (buy higher / sell lower to close).
            adjusted_price = current_price * (1 + slippage) if is_buy else current_price * (1 - slippage)

            payload = {
                "wallet_address": self.wallet_address,
                "coin": symbol.upper(),
                "size": close_size,
                "price": adjusted_price,
                "is_buy": is_buy,
            }

            result = self._prepare_sign_execute("close", payload)

            logger.info(f"[SUCCESS] Nansen close executed: {symbol} {close_size} units @ ${current_price} (limit ${adjusted_price:.6f})")

            return ClosePositionResult(
                success=True,
                position_id=symbol.upper(),
                symbol=symbol.upper(),
                exit_price=current_price,
                pnl=None,
                pnl_percentage=None,
                order_id=result.get("orderId"),
                error=None,
            )
        except Exception as e:
            logger.error(f"Failed to close position via Nansen for {symbol}: {e}")
            return ClosePositionResult(
                success=False,
                position_id=symbol.upper(),
                symbol=symbol.upper(),
                exit_price=None,
                pnl=None,
                pnl_percentage=None,
                order_id=None,
                error=str(e),
            )
