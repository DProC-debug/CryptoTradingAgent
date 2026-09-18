"""Macro Analyst - Macro market indicators and ecosystem analysis"""

import logging
from datetime import datetime
from typing import Optional
from .base_analyst import BaseAnalyst, AnalysisResult

logger = logging.getLogger(__name__)


class MacroAnalyst(BaseAnalyst):
    """Analyzes macro market conditions and ecosystem trends"""

    def __init__(self, coingecko_api, llm_client=None):
        """Initialize macro analyst

        Args:
            coingecko_api: CoinGeckoAPI instance
            llm_client: LLM client for reasoning
        """
        super().__init__("macro", llm_client)
        self.coingecko = coingecko_api

    async def analyze(
        self,
        crypto_symbol: str,
        market_data: dict,
        additional_context: Optional[dict] = None,
    ) -> AnalysisResult:
        """Analyze macro market conditions using LLM reasoning

        Args:
            crypto_symbol: Symbol like BTC, ETH
            market_data: Market data from CoinGecko
            additional_context: Additional macro data

        Returns:
            AnalysisResult with LLM-powered macro analysis
        """
        try:
            # Fetch macro indicators
            btc_dominance = self._get_btc_dominance()
            market_phase = self._get_market_phase(crypto_symbol)
            market_sentiment = self._get_market_sentiment()
            altseason_prob = self._calculate_altseason_probability(btc_dominance)
            
            key_metrics = {
                "btc_dominance": btc_dominance,
                "market_phase": market_phase,
                "overall_sentiment": market_sentiment,
                "altseason_probability": altseason_prob,
            }

            # Use LLM for intelligent analysis
            if not self.llm_client:
                logger.warning("No LLM client available, using fallback")
                return AnalysisResult(
                    analyst_type="macro",
                    score=0.0,
                    confidence=0.0,
                    reasoning="LLM client unavailable",
                    key_metrics=key_metrics,
                    timestamp=datetime.utcnow().isoformat(),
                )

            history_note = ""
            if additional_context and additional_context.get("recent_loss_note"):
                history_note = additional_context["recent_loss_note"] + "\n\n"

            prompt = f"""Analyze the macro market conditions for {crypto_symbol} and provide a trading signal.

Macro Indicators:
- BTC Dominance: {btc_dominance:.1f}% (>55%=bearish for alts, <45%=bullish for alts)
- Market Phase: {market_phase} (accumulation/distribution/trending)
- Market Sentiment: {market_sentiment} (bullish/bearish/neutral)
- Altcoin Season Probability: {altseason_prob:.1%}
- Market Cap Rank: #{market_data.get('market_cap_rank', 'N/A')}

Crypto Context:
- Token: {crypto_symbol}
- Price: ${market_data.get('current_price', 'N/A')}
- 24h Change: {market_data.get('price_change_24h', 0)}%

{history_note}Based on macro market conditions and cycle analysis, provide your trading signal:
SIGNAL: [BUY/HOLD/SELL]
CONFIDENCE: [0-100]
REASONING: [Your macro analysis]"""

            response = await self.llm_client.ainvoke(
                [{"role": "user", "content": prompt}]
            )
            response_text = response.content
            
            # Parse response
            signal, confidence, reasoning = self._parse_llm_response(response_text)
            score = self._signal_to_score(signal)

            return AnalysisResult(
                analyst_type="macro",
                score=score,
                confidence=confidence / 100.0 if confidence else 0.5,
                reasoning=reasoning,
                key_metrics=key_metrics,
                timestamp=datetime.utcnow().isoformat(),
            )

        except Exception as e:
            logger.error(f"Macro analyst error: {e}")
            return AnalysisResult(
                analyst_type="macro",
                score=0.0,
                confidence=0.0,
                reasoning=f"Macro analysis error: {e}",
                key_metrics={"error": str(e)},
                timestamp=datetime.utcnow().isoformat(),
            )

    def _get_btc_dominance(self) -> float:
        """Get BTC dominance percentage
        
        Returns:
            BTC dominance (e.g., 50.5 for 50.5%)
        """
        # In production, would fetch from CoinGecko or other source
        return 52.3

    def _get_market_phase(self, symbol: str) -> str:
        """Determine current market cycle phase
        
        Args:
            symbol: Crypto symbol
            
        Returns:
            Phase: 'accumulation', 'markup', 'distribution', 'markdown'
        """
        # Simulate market phase
        # In production, would analyze on-chain metrics and price action
        phases = {
            "BTC": "markup",
            "ETH": "markup",
            "SOL": "distribution",
        }
        return phases.get(symbol, "neutral")

    def _get_market_sentiment(self) -> str:
        """Get overall crypto market sentiment
        
        Returns:
            'bullish', 'bearish', or 'neutral'
        """
        # In production, would aggregate multiple sentiment sources
        return "bullish"

    def _calculate_altseason_probability(self, btc_dominance: float) -> float:
        """Calculate probability of altseason
        
        Args:
            btc_dominance: BTC dominance percentage
            
        Returns:
            Probability 0.0 to 1.0
        """
        # Altseason likely when BTC dominance is low
        if btc_dominance < 40:
            return 0.9
        elif btc_dominance < 45:
            return 0.7
        elif btc_dominance < 50:
            return 0.5
        else:
            return 0.2

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
