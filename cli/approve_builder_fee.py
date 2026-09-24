#!/usr/bin/env python3
"""
One-time Hyperliquid builder-fee approval, via Nansen's prepare -> sign -> execute flow.

Reads everything from .env (never pass or hardcode a private key):
    NANSEN_API_KEY, PORTFOLIO_WALLET_HYPERLIQUID, PORTFOLIO_WALLET_PRIVATE_KEY

Usage:
    python cli/approve_builder_fee.py

Builder-fee approval is per wallet - run this again if you ever switch to a new wallet.
"""

import logging
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
        print(f"        Key signs as:      {trader.account.address}")
        print(f"        Wallet in .env is: {wallet_address}")
        print("        The approval must be signed by the wallet's own key - fix .env and retry.")
        return 1

    print(f"[INFO] Wallet: {wallet_address}")

    status = trader.get_builder_fee_status()
    print(f"[INFO] Current status: {status}")
    if status.get("approved"):
        print("[OK] Builder fee already approved - nothing to do.")
        return 0

    print("[INFO] Requesting, signing and executing approval...")
    try:
        result = trader.approve_builder_fee()
    except Exception as e:
        print(f"[ERROR] Approval failed: {e}")
        return 1

    print(f"[OK] Approval submitted: {result.get('status', 'ok')}")

    status = trader.get_builder_fee_status()
    if status.get("approved"):
        print("[SUCCESS] Builder fee approved. You can now run: python cli/autonomous_trader.py")
        return 0

    print(f"[WARN] Approval executed but status still shows: {status}")
    print("       Wait a few seconds and re-run this script to re-check.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
