"""Persistent trade-outcome history, used to warn analysts when a coin was recently
closed at a loss or liquidated.

Unlike autonomous_trading_loop.py's trades_today (which resets every calendar day and
on every process restart - it exists only for the daily-loss circuit breaker and trade
counter), this log is deliberately long-lived: it survives restarts and day rollovers
so a "liquidated 6 hours ago" fact isn't lost the moment the bot is bounced or midnight
passes. It only needs to answer one question - "was this symbol closed at a loss or
liquidated recently?" - so it stores a small rolling window (PRUNE_AFTER_DAYS) rather
than a full trade ledger.
"""

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

PRUNE_AFTER_DAYS = 7
LOSS_OUTCOMES = {"STOP_LOSS", "LIQUIDATED"}


class TradeHistory:
    """Rolling, crash-safe log of closed-trade outcomes, keyed by symbol."""

    def __init__(self, cache_dir: str):
        self.path = os.path.join(cache_dir, "trade_history.json")
        self.entries: list[dict] = []
        self._load()

    def _load(self):
        try:
            if not os.path.exists(self.path):
                return
            with open(self.path, "r") as f:
                self.entries = json.load(f)
        except Exception as e:
            logger.warning(f"[WARN] Could not load trade history, starting fresh: {e}")
            self.entries = []

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            cutoff = datetime.now() - timedelta(days=PRUNE_AFTER_DAYS)
            self.entries = [
                e for e in self.entries
                if datetime.fromisoformat(e["closed_at"]) >= cutoff
            ]
            tmp_path = self.path + ".tmp"
            with open(tmp_path, "w") as f:
                json.dump(self.entries, f, indent=2)
            os.replace(tmp_path, self.path)
        except Exception as e:
            logger.warning(f"[WARN] Could not persist trade history: {e}")

    def record_close(
        self,
        symbol: str,
        outcome: str,
        pnl: Optional[float] = None,
        pnl_percentage: Optional[float] = None,
    ):
        """Record a closed position's outcome. outcome is one of TAKE_PROFIT,
        STOP_LOSS, or LIQUIDATED (see LOSS_OUTCOMES for which count as a loss)."""
        self.entries.append({
            "symbol": symbol.upper(),
            "outcome": outcome,
            "pnl": pnl,
            "pnl_percentage": pnl_percentage,
            "closed_at": datetime.now().isoformat(),
        })
        self._save()
        logger.info(f"[HISTORY] Recorded {symbol} close: {outcome} (pnl={pnl})")

    def get_recent_loss(self, symbol: str, hours: int = 24) -> Optional[dict]:
        """Most recent STOP_LOSS/LIQUIDATED entry for this symbol within the lookback
        window, or None. Take-profits are intentionally excluded - only losses matter here."""
        cutoff = datetime.now() - timedelta(hours=hours)
        matches = [
            e for e in self.entries
            if e["symbol"] == symbol.upper()
            and e["outcome"] in LOSS_OUTCOMES
            and datetime.fromisoformat(e["closed_at"]) >= cutoff
        ]
        if not matches:
            return None
        return max(matches, key=lambda e: e["closed_at"])

    def format_prompt_note(self, symbol: str, hours: int = 24) -> str:
        """A short, analyst-facing note if this symbol has a recent loss/liquidation,
        else "". Meant to be prepended into an analyst's LLM prompt."""
        entry = self.get_recent_loss(symbol, hours=hours)
        if not entry:
            return ""

        closed_at = datetime.fromisoformat(entry["closed_at"])
        hours_ago = (datetime.now() - closed_at).total_seconds() / 3600
        outcome = entry["outcome"]

        if outcome == "LIQUIDATED":
            detail = f"This position was LIQUIDATED {hours_ago:.1f} hours ago."
        else:
            pnl = entry.get("pnl")
            pnl_pct = entry.get("pnl_percentage")
            pnl_str = f" (${pnl:.2f}" + (f", {pnl_pct * 100:.1f}%)" if pnl_pct is not None else ")") if pnl is not None else ""
            detail = f"This position hit its STOP LOSS {hours_ago:.1f} hours ago{pnl_str}."

        return (
            "IMPORTANT - RECENT TRADING HISTORY FOR THIS COIN:\n"
            f"{detail} Weigh this into your risk assessment - repeated losses on the "
            "same coin in a short window are a signal on their own, not just noise."
        )
