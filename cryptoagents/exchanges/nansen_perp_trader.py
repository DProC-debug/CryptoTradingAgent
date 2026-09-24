"""
Hyperliquid Perpetuals Trading via Nansen API
Routes all trading through Nansen's prepare -> sign -> execute flow (docs.nansen.ai/api/trade/perp-trading)
Keys never leave this process: Nansen returns unsigned EIP-712 typed data, we sign locally, we submit the signature.
"""

import logging
import math
import time
from typing import Dict, Optional, List, Tuple
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
    HL_INFO_URL = "https://api.hyperliquid.xyz/info"
    UNIVERSE_TTL_SECONDS = 3600
    # Hyperliquid lists very low-priced coins as "k" coins (kPEPE, kBONK...): one unit = 1000 tokens,
    # so its price is 1000x the CoinGecko price and its size is 1/1000 of the token count.
    K_COIN_SCALE = 1000

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
        self._universe: Optional[Dict[str, dict]] = None
        self._universe_at = 0.0
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
            "coin": (self._resolve(symbol) or (symbol.upper(), 1))[0],
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
            "coin": (self._resolve(symbol) or (symbol.upper(), 1))[0],
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
            # Standard (non-unified) accounts hold margin in the perps balance instead: spotUsdc is
            # ~0 there and the funds show up as marginSummary.accountValue / withdrawable. Take the
            # larger of the two views so both account modes read correctly (max, not sum - in
            # unified mode the perps fields are only a sub-ledger of the same spot funds).
            perp_value = float((data.get("marginSummary") or {}).get("accountValue", 0) or 0)
            withdrawable = float(data.get("withdrawable", 0) or 0)
            total_collateral = max(spot_usdc, perp_value)
            free_collateral = max(0.0, spot_usdc - margin_used, withdrawable)

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

    # ------------------------------------------------------------------
    # Hyperliquid asset list: which coins exist, their max leverage / size precision,
    # and the CoinGecko-symbol <-> Hyperliquid-name translation ("PEPE" <-> "kPEPE")
    # ------------------------------------------------------------------

    def _get_universe(self) -> Dict[str, dict]:
        """Live, non-delisted Hyperliquid assets keyed by name, cached for an hour.

        Empty if Hyperliquid is unreachable (retried after 60s) - callers then skip listing
        checks rather than blocking trades on a metadata hiccup.
        """
        now = time.time()
        if self._universe is not None and now - self._universe_at < self.UNIVERSE_TTL_SECONDS:
            return self._universe
        try:
            response = requests.post(self.HL_INFO_URL, json={"type": "meta"}, timeout=10)
            response.raise_for_status()
            self._universe = {a["name"]: a for a in response.json()["universe"] if not a.get("isDelisted")}
            self._universe_at = now
        except Exception as e:
            logger.warning(f"Could not load Hyperliquid asset list: {e}")
            self._universe = self._universe or {}
            self._universe_at = now - self.UNIVERSE_TTL_SECONDS + 60
        return self._universe

    def _resolve(self, symbol: str) -> Optional[Tuple[str, int]]:
        """CoinGecko symbol -> (Hyperliquid name, price scale), or None if not listed."""
        symbol = symbol.upper()
        universe = self._get_universe()
        if not universe or symbol in universe:
            return symbol, 1
        if f"k{symbol}" in universe:
            return f"k{symbol}", self.K_COIN_SCALE
        return None

    def _to_base(self, hl_name: str) -> Tuple[str, int]:
        """Hyperliquid name -> (CoinGecko symbol, price scale). Inverse of _resolve()."""
        if hl_name[:1] == "k" and hl_name[1:].isupper() and hl_name[1:] not in self._get_universe():
            return hl_name[1:], self.K_COIN_SCALE
        return hl_name, 1

    def get_tradable_symbols(self) -> Optional[set]:
        """CoinGecko-style symbols Hyperliquid lists, or None if the asset list is unavailable."""
        universe = self._get_universe()
        if not universe:
            return None
        return {self._to_base(name)[0] for name in universe}

    def get_max_leverage(self, symbol: str) -> Optional[int]:
        """Hyperliquid's per-coin leverage ceiling (e.g. LIT 5x, PUMP 10x, BTC 40x), or None if unknown."""
        resolved = self._resolve(symbol)
        if resolved is None:
            return None
        asset = self._get_universe().get(resolved[0])
        return int(asset["maxLeverage"]) if asset and asset.get("maxLeverage") else None

    def get_account_mode(self) -> str:
        """'unified', 'standard' or 'unknown', from Hyperliquid's public userAbstraction lookup."""
        try:
            response = requests.post(
                self.HL_INFO_URL,
                json={"type": "userAbstraction", "user": self.wallet_address},
                timeout=10,
            )
            response.raise_for_status()
            mode = str(response.json()).strip().lower()
        except Exception as e:
            logger.warning(f"Could not determine Hyperliquid account mode: {e}")
            return "unknown"

        if mode in ("unifiedaccount", "portfoliomargin"):
            return "unified"
        if mode in ("default", "disabled"):
            return "standard"
        return "unknown"

    def ensure_perps_margin(self, min_usd: float = 1.0) -> Optional[dict]:
        """Standard accounts only: move idle spot USDC into the perps balance so orders have margin.

        Unified accounts already margin from spot (Hyperliquid rejects the transfer there), so
        they're left alone. If the mode can't be read, the transfer is attempted and a
        "unified account" rejection is treated as "nothing to do". Only ever moves USDC
        spot -> perps inside the same wallet; never withdraws.
        """
        mode = self.get_account_mode()
        if mode == "unified":
            return None

        raw = self.get_account_balance().get("raw") or {}
        spot_usdc = float(raw.get("spotUsdc", 0) or 0)
        if spot_usdc < min_usd:
            return None

        amount = math.floor(spot_usdc * 100) / 100
        logger.info(f"Account mode '{mode}': moving ${amount:,.2f} spot USDC to perps margin")
        try:
            return self.transfer_to_perps(amount)
        except Exception as e:
            if "unified" in str(e).lower():
                logger.info("Unified account detected - spot USDC already counts as margin")
            else:
                logger.warning(f"Could not move spot USDC to perps: {e}")
            return None

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

                coin_name = pos.get("coin", pos.get("symbol", ""))
                base_symbol, scale = self._to_base(coin_name)
                # Prices are reported in CoinGecko units (kPEPE is 1000x); size stays in native
                # exchange units so close_position() closes exactly what is open.
                entry_price = float(pos.get("entryPrice", pos.get("entryPx", 0)) or 0) / scale
                current_price = float(pos.get("markPrice", pos.get("markPx", 0)) or 0) / scale or entry_price
                leverage_field = pos.get("leverage", 1)
                leverage = int(leverage_field.get("value", 1)) if isinstance(leverage_field, dict) else int(float(leverage_field or 1))
                margin_used = float(pos.get("marginUsed", 0) or 0)
                unrealized_pnl = float(pos.get("unrealizedPnl", 0) or 0)
                funding_paid = float((pos.get("cumFunding") or {}).get("sinceOpen", 0) or 0)

                # Prefer Hyperliquid's own returnOnEquity (return on margin) - pnl/notional
                # understates real P&L% by roughly `leverage`x and would make TP/SL never fire.
                if pos.get("returnOnEquity") is not None:
                    pnl_pct = float(pos["returnOnEquity"]) * 100
                elif margin_used:
                    pnl_pct = (unrealized_pnl / margin_used) * 100
                else:
                    pnl_pct = 0

                open_positions.append(PositionData(
                    position_id=f"{coin_name}_{size}",
                    symbol=base_symbol,
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
                    funding_paid=funding_paid,
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
            resolved = self._resolve(symbol)
            if resolved is None:
                raise RuntimeError(f"{symbol.upper()} is not listed on Hyperliquid")
            hl_coin, scale = resolved
            hl_price = price * scale
            decimals = (self._get_universe().get(hl_coin) or {}).get(
                "szDecimals", self.ASSET_PRECISION.get(symbol.upper(), 4)
            )
            asset_size = round(size_usd / hl_price, decimals)
            if asset_size <= 0:
                raise RuntimeError(
                    f"${size_usd:.2f} is too small to trade {hl_coin} (rounds to zero at {decimals} size decimals)"
                )

            payload = {
                "wallet_address": self.wallet_address,
                "coin": hl_coin,
                "is_buy": is_buy,
                "size": asset_size,
                "price": hl_price,
                "order_type": order_type,
                "slippage": slippage,
            }

            result = self._prepare_sign_execute("order", payload)
            prepared = result["_prepared"]
            echoed_price = float(prepared.get("price") or hl_price) / scale
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
            hl_coin, scale = self._resolve(symbol) or (symbol.upper(), 1)
            hl_price = current_price * scale
            adjusted_price = hl_price * (1 + slippage) if is_buy else hl_price * (1 - slippage)

            payload = {
                "wallet_address": self.wallet_address,
                "coin": hl_coin,
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
