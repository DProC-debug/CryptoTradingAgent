"""Sentiment Analyst - Social sentiment and community analysis"""

import logging
from datetime import datetime
from typing import Optional
from .base_analyst import BaseAnalyst, AnalysisResult

logger = logging.getLogger(__name__)


class SentimentAnalyst(BaseAnalyst):
    """Analyzes social sentiment and community metrics"""

    def __init__(self, llm_client=None):
        """Initialize sentiment analyst

        Args:
            llm_client: LLM client for reasoning
        """
        super().__init__("sentiment", llm_client)
        # In production, would integrate with:
        # - Twitter/X API for sentiment
        # - Reddit API for discussions
        # - Discord for community activity
        # - LunarCrush, IntoTheBlock, etc.

    async def analyze(
        self,
        crypto_symbol: str,
        market_data: dict,
        additional_context: Optional[dict] = None,
    ) -> AnalysisResult:
        """Analyze sentiment using LLM reasoning

        Args:
            crypto_symbol: Symbol like BTC, ETH
            market_data: Market data from CoinGecko
            additional_context: Additional sentiment data

        Returns:
            AnalysisResult with LLM-powered sentiment analysis
        """
        try:
            if not self.llm_client:
                logger.warning("No LLM client available, using fallback")
                return AnalysisResult(
                    analyst_type="sentiment",
                    score=0.0,
                    confidence=0.0,
                    reasoning="LLM client unavailable",
                    key_metrics={},
                    timestamp=datetime.utcnow().isoformat(),
                )

            price_change = market_data.get("price_change_24h", 0)
            volume_24h = market_data.get("volume_24h", 0)
            circulating_supply = market_data.get("circulating_supply")
            
            # Format circulating supply safely
            supply_str = f"{circulating_supply:,.0f}" if circulating_supply and isinstance(circulating_supply, (int, float)) else "N/A"

            prompt = f"""Analyze the market sentiment for {crypto_symbol} and provide a trading signal.

Market Indicators:
- 24h Price Change: {price_change:.2f}%
- Current Price: ${market_data.get('current_price', 'N/A')}
- 24h Volume: ${volume_24h:,.0f}
- Market Cap Rank: #{market_data.get('market_cap_rank', 'N/A')}
- Circulating Supply: {supply_str}

Based on current market sentiment, momentum, and community activity, provide your analysis:
SIGNAL: [BUY/HOLD/SELL]
CONFIDENCE: [0-100]
REASONING: [Your sentiment analysis]"""

            response = await self.llm_client.ainvoke(
                [{"role": "user", "content": prompt}]
            )
            response_text = response.content
            
            # Parse response
            signal, confidence, reasoning = self._parse_llm_response(response_text)
            score = self._signal_to_score(signal)

            return AnalysisResult(
                analyst_type="sentiment",
                score=score,
                confidence=confidence / 100.0 if confidence else 0.5,
                reasoning=reasoning,
                key_metrics={"price_change_24h": price_change, "volume_24h": volume_24h},
                timestamp=datetime.utcnow().isoformat(),
            )

        except Exception as e:
            logger.error(f"Sentiment analyst error: {e}")
            return AnalysisResult(
                analyst_type="sentiment",
                score=0.0,
                confidence=0.0,
                reasoning=f"Sentiment analysis error: {e}",
                key_metrics={"error": str(e)},
                timestamp=datetime.utcnow().isoformat(),
            )

    def _calculate_sentiment_score(self, symbol: str) -> float:
        """Calculate sentiment score (-1.0 to 1.0)
        
        Args:
            symbol: Crypto symbol
            
        Returns:
            Sentiment score
        """
        # Simulate sentiment based on symbol
        # In production, would aggregate real API data
        sentiment_map = {
            "BTC": 0.65,   # Generally bullish
            "ETH": 0.55,   # Moderately bullish
            "SOL": 0.45,   # Neutral-bullish
            "DOGE": 0.35,  # Mixed
        }
        
        return sentiment_map.get(symbol, 0.2)

    def _get_dominant_emotion(self, sentiment: float) -> str:
        """Get dominant emotion from sentiment score"""
        if sentiment > 0.6:
            return "FOMO/Euphoria"
        elif sentiment > 0.2:
            return "Optimism"
        elif sentiment < -0.6:
            return "Fear/Panic"
        elif sentiment < -0.2:
            return "Pessimism"
        else:
            return "Neutral/Mixed"

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
