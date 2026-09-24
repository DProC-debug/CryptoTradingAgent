#!/usr/bin/env python3
"""
Move USDC from your Hyperliquid spot balance to the perps balance (the only one usable as margin).

Reads NANSEN_API_KEY, PORTFOLIO_WALLET_HYPERLIQUID and PORTFOLIO_WALLET_PRIVATE_KEY from .env.

Usage:
    python cli/transfer_usdc_to_perps.py            # move all spot USDC
    python cli/transfer_usdc_to_perps.py 50         # move 50 USDC

Not needed (and rejected by Hyperliquid) if your account is in Unified Account mode.
"""

import logging
import math
import os
import sys

from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from cryptoagents.exchanges.nansen_perp_trader import NansenPerpTrader  # noqa: E402

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def main() -> int:
    api_key = os.getenv("NANSEN_API_KEY")
    wallet_address = os.getenv("PORTFOLIO_WALLET_HYPERLIQUID")
    private_key = os.getenv("PORTFOLIO_WALLET_PRIVATE_KEY")

    missing = [
        name
        for name, value in (
            ("NANSEN_API_KEY", api_key),
            ("PORTFOLIO_WALLET_HYPERLIQUID", wallet_address),
            ("PORTFOLIO_WALLET_PRIVATE_KEY", private_key),
        )
        if not value
    ]
    if missing:
        print(f"[ERROR] Missing in .env: {', '.join(missing)}")
        return 1

    trader = NansenPerpTrader(api_key, wallet_address, private_key)

    if trader.account.address.lower() != wallet_address.lower():
        print("[ERROR] PORTFOLIO_WALLET_PRIVATE_KEY does not belong to PORTFOLIO_WALLET_HYPERLIQUID.")
        return 1

    raw = trader.get_account_balance().get("raw", {})
    spot = float(raw.get("spotUsdc", 0) or 0)
    perps = float((raw.get("marginSummary") or {}).get("accountValue", 0) or 0)
    print(f"[INFO] Spot USDC: ${spot:,.2f}   Perps USDC: ${perps:,.2f}")

    amount = float(sys.argv[1]) if len(sys.argv) > 1 else math.floor(spot * 100) / 100
    if amount <= 0 or amount > spot:
        print(f"[ERROR] Nothing valid to transfer (amount ${amount:,.2f}, spot ${spot:,.2f}).")
        return 1

    print(f"[INFO] Transferring ${amount:,.2f} spot -> perps...")
    try:
        trader.transfer_to_perps(amount)
    except Exception as e:
        print(f"[ERROR] Transfer failed: {e}")
        return 1

    raw = trader.get_account_balance().get("raw", {})
    print(
        f"[OK] Spot USDC: ${float(raw.get('spotUsdc', 0) or 0):,.2f}   "
        f"Perps USDC: ${float((raw.get('marginSummary') or {}).get('accountValue', 0) or 0):,.2f}"
    )
    print("[SUCCESS] You can now run: python cli/autonomous_trader.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
