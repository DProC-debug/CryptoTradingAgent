"""Blockchain Analyst - On-chain metrics and whale movement analysis"""

import logging
from datetime import datetime
from typing import Optional
from .base_analyst import BaseAnalyst, AnalysisResult

logger = logging.getLogger(__name__)


class BlockchainAnalyst(BaseAnalyst):
    """Analyzes Hyperliquid perp positioning by trader cohort (Smart Money, Whales, Public Figures) using Nansen"""

    def __init__(self, nansen_api, llm_client=None):
        """Initialize blockchain analyst

        Args:
            nansen_api: NansenAPI instance
            llm_client: LLM client for deep reasoning
        """
        super().__init__("blockchain", llm_client)
        self.nansen = nansen_api

    async def analyze(
        self,
        crypto_symbol: str,
        market_data: dict,
        additional_context: Optional[dict] = None,
    ) -> AnalysisResult:
        """Analyze Hyperliquid perp positioning using LLM reasoning

        Args:
            crypto_symbol: Symbol like BTC, ETH
            market_data: Market data from CoinGecko
            additional_context: Unused

        Returns:
            AnalysisResult with LLM-powered positioning analysis
        """
        try:
            positioning = self.nansen.get_token_position_intelligence(crypto_symbol)
            if not positioning or not any(positioning.values()):
                return self._create_no_data_result()

            smart_longs = positioning.get("smart_trader_longs_usd", 0)
            smart_shorts = positioning.get("smart_trader_shorts_usd", 0)
            whale_longs = positioning.get("whale_longs_usd", 0)
            whale_shorts = positioning.get("whale_shorts_usd", 0)
            public_longs = positioning.get("public_figure_longs_usd", 0)
            public_shorts = positioning.get("public_figure_shorts_usd", 0)

            def net_ratio(longs: float, shorts: float) -> float:
                total = longs + shorts
                return (longs - shorts) / total if total > 0 else 0.0

            smart_money_ratio = net_ratio(smart_longs, smart_shorts)
            whale_ratio = net_ratio(whale_longs, whale_shorts)
            public_figure_ratio = net_ratio(public_longs, public_shorts)

            key_metrics = {
                "smart_money_net_ratio": smart_money_ratio,
                "smart_money_longs_usd": smart_longs,
                "smart_money_shorts_usd": smart_shorts,
                "whale_net_ratio": whale_ratio,
                "whale_longs_usd": whale_longs,
                "whale_shorts_usd": whale_shorts,
                "public_figure_net_ratio": public_figure_ratio,
            }

            # Use LLM for intelligent analysis
            if not self.llm_client:
                logger.warning("No LLM client available, using fallback")
                return self._create_no_data_result()

            prompt = f"""Analyze Hyperliquid perpetual positioning for {crypto_symbol} and provide a trading signal.

Positioning by Trader Cohort (net long/short USD exposure, -1.0 = fully short, +1.0 = fully long):
- Smart Money: {smart_money_ratio:+.2f} (${smart_longs:,.0f} long vs ${smart_shorts:,.0f} short)
- Whales: {whale_ratio:+.2f} (${whale_longs:,.0f} long vs ${whale_shorts:,.0f} short)
- Public Figures: {public_figure_ratio:+.2f} (${public_longs:,.0f} long vs ${public_shorts:,.0f} short)

Market Data:
- Current Price: ${market_data.get('current_price', market_data.get('usd', 'N/A'))}
- 24h Volume: ${market_data.get('volume_24h', 'N/A')}
- 24h Change: {market_data.get('price_change_24h', 'N/A')}%

Weigh Smart Money positioning most heavily - it has historically been the most predictive cohort.
Provide your analysis in this format:
SIGNAL: [BUY/HOLD/SELL]
CONFIDENCE: [0-100]
REASONING: [Your detailed analysis]"""

            response = await self.llm_client.ainvoke(
                [{"role": "user", "content": prompt}]
            )
            response_text = response.content
            
            # Parse LLM response
            signal, confidence, reasoning = self._parse_llm_response(response_text)
            score = self._signal_to_score(signal)

            return AnalysisResult(
                analyst_type="blockchain",
                score=score,
                confidence=confidence / 100.0 if confidence else 0.5,
                reasoning=reasoning,
                key_metrics=key_metrics,
                timestamp=datetime.utcnow().isoformat(),
            )

        except Exception as e:
            logger.error(f"Blockchain analyst error: {e}")
            return self._create_error_result(str(e))

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

    def _create_no_data_result(self) -> AnalysisResult:
        """Create result when data unavailable"""
        return AnalysisResult(
            analyst_type="blockchain",
            score=0.0,
            confidence=0.0,
            reasoning="Blockchain data unavailable for this cryptocurrency",
            key_metrics={},
            timestamp=datetime.utcnow().isoformat(),
        )

    def _create_error_result(self, error: str) -> AnalysisResult:
        """Create result when error occurs"""
        return AnalysisResult(
            analyst_type="blockchain",
            score=0.0,
            confidence=0.0,
            reasoning=f"Blockchain analysis error: {error}",
            key_metrics={"error": error},
            timestamp=datetime.utcnow().isoformat(),
        )
