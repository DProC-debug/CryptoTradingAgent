"""Fundamental Analyst - Project fundamentals and tokenomics analysis"""

import logging
from datetime import datetime
from typing import Optional
from .base_analyst import BaseAnalyst, AnalysisResult

logger = logging.getLogger(__name__)


class FundamentalAnalyst(BaseAnalyst):
    """Analyzes project fundamentals using real CoinGecko supply/sentiment/watchlist data"""

    def __init__(self, coingecko_api=None, llm_client=None):
        """Initialize fundamental analyst

        Args:
            coingecko_api: CoinGeckoAPI instance for supply/sentiment/watchlist data
            llm_client: LLM client for reasoning
        """
        super().__init__("fundamental", llm_client)
        self.coingecko_api = coingecko_api

    async def analyze(
        self,
        crypto_symbol: str,
        market_data: dict,
        additional_context: Optional[dict] = None,
    ) -> AnalysisResult:
        """Analyze project fundamentals using LLM reasoning

        Args:
            crypto_symbol: Symbol like BTC, ETH
            market_data: Market data from CoinGecko (must include 'id' for coin lookup)
            additional_context: Unused

        Returns:
            AnalysisResult with LLM-powered fundamental analysis
        """
        try:
            coin_id = market_data.get("id")
            details = self.coingecko_api.get_coin_details(coin_id) if (coin_id and self.coingecko_api) else {}
            if not details:
                return self._create_no_data_result()

            key_metrics = self._extract_fundamentals(details)

            # Use LLM for intelligent analysis
            if not self.llm_client:
                logger.warning("No LLM client available, using fallback")
                return self._create_no_data_result()

            categories = ", ".join(key_metrics["categories"]) if key_metrics["categories"] else "N/A"

            prompt = f"""Analyze the fundamentals for {crypto_symbol} and provide a trading signal.

Supply & Dilution (real data from CoinGecko):
- Circulating Supply: {key_metrics['circulating_supply']}
- Total Supply: {key_metrics['total_supply']}
- Max Supply: {key_metrics['max_supply']}
- Circulating % of Total: {key_metrics['pct_circulating']}
- FDV / Market Cap Ratio: {key_metrics['fdv_to_mcap_ratio']} (>1 means significant future dilution ahead; ~1 means mostly fully diluted already)

Community Signals (real data from CoinGecko):
- Community Sentiment (up votes): {key_metrics['sentiment_up_pct']}
- Watchlist Users: {key_metrics['watchlist_users']} (people tracking this coin)
- Categories: {categories}
- Market Cap Rank: #{key_metrics['market_cap_rank']}

Based on supply dynamics and community signals, provide your trading signal:
SIGNAL: [BUY/HOLD/SELL]
CONFIDENCE: [0-100]
REASONING: [Your fundamental analysis]"""

            response = await self.llm_client.ainvoke(
                [{"role": "user", "content": prompt}]
            )
            response_text = response.content
            
            # Parse response
            signal, confidence, reasoning = self._parse_llm_response(response_text)
            score = self._signal_to_score(signal)

            return AnalysisResult(
                analyst_type="fundamental",
                score=score,
                confidence=confidence / 100.0 if confidence else 0.5,
                reasoning=reasoning,
                key_metrics=key_metrics,
                timestamp=datetime.utcnow().isoformat(),
            )

        except Exception as e:
            logger.error(f"Fundamental analyst error: {e}")
            return AnalysisResult(
                analyst_type="fundamental",
                score=0.0,
                confidence=0.0,
                reasoning=f"Fundamental analysis error: {e}",
                key_metrics={"error": str(e)},
                timestamp=datetime.utcnow().isoformat(),
            )

    def _extract_fundamentals(self, details: dict) -> dict:
        """Pull real, freely-available fields out of a CoinGecko coin detail record

        Note: developer_data/community_data (github/twitter stats) are empty on the
        free tier - only market_data, sentiment votes, watchlist, and categories are used.
        """
        market = details.get("market_data", {}) or {}

        circulating = market.get("circulating_supply") or 0
        total = market.get("total_supply")
        max_supply = market.get("max_supply")
        fdv = (market.get("fully_diluted_valuation") or {}).get("usd")
        mcap = (market.get("market_cap") or {}).get("usd")

        pct_circulating = round(circulating / total * 100, 1) if total else None
        fdv_to_mcap = round(fdv / mcap, 2) if fdv and mcap else None

        return {
            "circulating_supply": circulating,
            "total_supply": total,
            "max_supply": max_supply,
            "pct_circulating": pct_circulating,
            "fdv_to_mcap_ratio": fdv_to_mcap,
            "sentiment_up_pct": details.get("sentiment_votes_up_percentage"),
            "watchlist_users": details.get("watchlist_portfolio_users"),
            "categories": [c for c in (details.get("categories") or []) if c],
            "market_cap_rank": details.get("market_cap_rank"),
        }

    def _create_no_data_result(self) -> AnalysisResult:
        """Create result when coin details are unavailable"""
        return AnalysisResult(
            analyst_type="fundamental",
            score=0.0,
            confidence=0.0,
            reasoning="Fundamental data unavailable for this cryptocurrency",
            key_metrics={},
            timestamp=datetime.utcnow().isoformat(),
        )

    def _parse_llm_response(self, response: str) -> tuple:
        """Parse LLM response to extract signal, confidence, reasoning"""
        import re
        lines = response.split('\n')
        signal = "HOLD"
        confidence = 50
        reasoning = response

        for line in lines:
            # Strip markdown formatting (**bold**, #headers, `code`) some models wrap labels in
            clean_line = re.sub(r"[*#`]", "", line)
            if "SIGNAL:" in clean_line:
                token = clean_line.split("SIGNAL:")[1].strip().split()[0] if clean_line.split("SIGNAL:")[1].strip() else ""
                token = re.sub(r"[^A-Za-z]", "", token).upper()
                if token in ("BUY", "SELL", "HOLD"):
                    signal = token
            elif "CONFIDENCE:" in clean_line:
                match = re.search(r"\d+", clean_line.split("CONFIDENCE:")[1])
                if match:
                    confidence = int(match.group())
            elif "REASONING:" in clean_line:
                reasoning = clean_line.split("REASONING:")[1].strip()

        return signal, confidence, reasoning

    def _signal_to_score(self, signal: str) -> float:
        """Convert signal to -1.0 to 1.0 score"""
        if signal == "BUY":
            return 0.8
        elif signal == "SELL":
            return -0.8
        else:
            return 0.0
