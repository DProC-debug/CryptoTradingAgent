"""Export real bot state (positions, balance, recent verdicts) as JSON for the
web dashboard. Read-only: never places, closes, or modifies anything.

Usage:
    python web/export_state.py [--out web/state_export.json] [--log-lines 6000] [--history 20]
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

load_dotenv(PROJECT_ROOT / ".env")

from cryptoagents.exchanges.hyperliquid_trader import HyperliquidTrader
from cryptoagents.exchanges.nansen_perp_trader import NansenPerpTrader


def build_trader():
    """Instantiate the same backend the live bot uses, read-only usage only."""
    backend = os.getenv("TRADING_BACKEND", "nansen").lower()
    wallet_address = os.getenv("PORTFOLIO_WALLET_HYPERLIQUID", "")
    wallet_private_key = os.getenv("PORTFOLIO_WALLET_PRIVATE_KEY", "")
    max_leverage = int(os.getenv("HYPERLIQUID_MAX_LEVERAGE", "20"))

    if not wallet_address or not wallet_private_key:
        raise RuntimeError("Missing PORTFOLIO_WALLET_HYPERLIQUID or PORTFOLIO_WALLET_PRIVATE_KEY in .env")

    if backend == "nansen":
        nansen_api_key = os.getenv("NANSEN_API_KEY", "")
        if not nansen_api_key:
            raise RuntimeError("Missing NANSEN_API_KEY - required for TRADING_BACKEND=nansen")
        return NansenPerpTrader(
            api_key=nansen_api_key,
            wallet_address=wallet_address,
            wallet_private_key=wallet_private_key,
            max_leverage=max_leverage,
        )
    return HyperliquidTrader(
        wallet_address=wallet_address,
        wallet_private_key=wallet_private_key,
        max_leverage=max_leverage,
    )


def export_positions(trader) -> list:
    positions = trader.get_open_positions()
    out = []
    for p in positions:
        price_move_pct = ((p.current_price - p.entry_price) / p.entry_price) * 100 if p.entry_price else 0
        if p.side.value == "SHORT":
            price_move_pct = -price_move_pct
        out.append({
            "symbol": p.symbol,
            "side": p.side.value,
            "size": p.size,
            "entryPrice": p.entry_price,
            "currentPrice": p.current_price,
            "leverage": p.leverage,
            "unrealizedPnl": round(p.unrealized_pnl, 2),
            "priceMovePct": round(price_move_pct, 2),
            "fundingPaid": round(p.funding_paid, 2),
        })
    return out


def export_today_trades(state_file: Path) -> list:
    if not state_file.exists():
        return []
    try:
        data = json.loads(state_file.read_text())
    except Exception:
        return []
    out = []
    for t in data.get("trades_today", []):
        out.append({
            "symbol": t.get("symbol"),
            "signal": t.get("signal"),
            "confidence": t.get("confidence"),
            "entryPrice": t.get("entry_price"),
            "leverage": t.get("leverage"),
            "status": t.get("status"),
            "pnl": t.get("pnl"),
            "timestamp": t.get("timestamp"),
        })
    return out


VERDICT_RE = re.compile(
    r"Propagating analysis for (?P<symbol>\S+) on"
)
SCORE_RE = re.compile(
    r"\[SCORE\] debate_score=(?P<debate>-?[\d.]+) synthesized_score=(?P<synth>-?[\d.]+) combined_score=(?P<combined>-?[\d.]+)"
)
DECISION_RE = re.compile(
    r"Trading decision: (?P<signal>BUY|SELL|HOLD) \(confidence: (?P<confidence>[\d.]+)%\)"
)
RISK_RE = re.compile(
    r"Risk assessment: Position adjusted to (?P<size>\d+)%"
)
TIMESTAMP_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")


def export_recent_verdicts(log_file: Path, tail_lines: int, limit: int) -> list:
    """Reconstruct recent (symbol, signal, confidence, score) verdicts by scanning
    the tail of the log for the same sequence of lines each analysis cycle emits."""
    if not log_file.exists():
        return []

    with open(log_file, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()[-tail_lines:]

    verdicts = []
    current_symbol = None
    current_ts = None
    current_score = None

    for line in lines:
        m = TIMESTAMP_RE.match(line)
        ts = m.group(1) if m else current_ts

        m = VERDICT_RE.search(line)
        if m:
            current_symbol = m.group("symbol")
            current_ts = ts
            current_score = None
            continue

        m = SCORE_RE.search(line)
        if m:
            current_score = m.group("combined")
            continue

        m = DECISION_RE.search(line)
        if m and current_symbol:
            verdicts.append({
                "symbol": current_symbol,
                "signal": m.group("signal"),
                "confidence": round(float(m.group("confidence"))),
                "score": current_score,
                "size": None,
                "timestamp": current_ts,
            })
            continue

        m = RISK_RE.search(line)
        if m and verdicts and verdicts[-1]["symbol"] == current_symbol and verdicts[-1]["size"] is None:
            verdicts[-1]["size"] = m.group("size") + "%"

    verdicts.reverse()
    return verdicts[:limit]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(PROJECT_ROOT / "web" / "state_export.json"))
    parser.add_argument("--log-lines", type=int, default=6000, help="How many lines to scan from the end of the log")
    parser.add_argument("--history", type=int, default=20, help="Max recent verdicts to include")
    args = parser.parse_args()

    trader = build_trader()
    balance_info = trader.get_account_balance()
    positions = export_positions(trader)
    state_file = PROJECT_ROOT / "cache" / "autonomous_trader_state.json"
    today_trades = export_today_trades(state_file)
    recent_verdicts = export_recent_verdicts(
        PROJECT_ROOT / "autonomous_trader.log", args.log_lines, args.history
    )
    cycle_count = None
    if state_file.exists():
        try:
            cycle_count = json.loads(state_file.read_text()).get("cycle_count")
        except Exception:
            pass

    payload = {
        "accountBalance": balance_info.get("total_collateral", 0),
        "freeCollateral": balance_info.get("free_collateral", 0),
        "cycleCount": cycle_count,
        "positions": positions,
        "todayTrades": today_trades,
        "recentVerdicts": recent_verdicts,
        "exportedAt": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
    }

    out_path = Path(args.out)
    out_path.write_text(json.dumps(payload, indent=2))
    print(f"Wrote {out_path}")
    print(f"  Account balance: ${payload['accountBalance']:.2f}")
    print(f"  Open positions: {len(positions)}")
    print(f"  Today's trades: {len(today_trades)}")
    print(f"  Recent verdicts parsed: {len(recent_verdicts)}")


if __name__ == "__main__":
    main()
