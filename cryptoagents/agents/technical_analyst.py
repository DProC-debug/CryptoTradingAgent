"""Technical Analyst - Price action and technical indicators analysis"""

import logging
from datetime import datetime
from typing import Optional
import pandas as pd
from .base_analyst import BaseAnalyst, AnalysisResult

logger = logging.getLogger(__name__)


class TechnicalAnalyst(BaseAnalyst):
    """Analyzes technical indicators and price action"""

    def __init__(self, coingecko_api=None, llm_client=None):
        """Initialize technical analyst

        Args:
            coingecko_api: CoinGeckoAPI instance for historical price data
            llm_client: LLM client for reasoning
        """
        super().__init__("technical", llm_client)
        self.coingecko_api = coingecko_api

    async def analyze(
        self,
        crypto_symbol: str,
        market_data: dict,
        additional_context: Optional[dict] = None,
    ) -> AnalysisResult:
        """Analyze technical indicators using LLM reasoning

        Args:
            crypto_symbol: Symbol like BTC, ETH
            market_data: Market data from CoinGecko
            additional_context: Historical price data if available

        Returns:
            AnalysisResult with LLM-powered technical analysis
        """
        try:
            current_price = market_data.get("current_price", market_data.get("usd", 0))
            if not current_price:
                return self._create_no_data_result()

            # Fetch real historical closes for indicator calculation
            prices = self._fetch_price_history(market_data.get("id"))
            indicators = self._calculate_indicators(current_price, crypto_symbol, prices)
            
            key_metrics = {
                "current_price": current_price,
                "rsi": indicators["rsi"],
                "macd": indicators["macd"],
                "price_to_bb": indicators["price_to_bb"],
                "trend": indicators["trend"],
            }

            # Use LLM for intelligent analysis
            if not self.llm_client:
                logger.warning("No LLM client available, using fallback")
                return self._create_no_data_result()

            prompt = f"""Analyze the technical indicators for {crypto_symbol} and provide a trading signal.

Technical Indicators:
- Current Price: ${current_price}
- RSI: {indicators['rsi']:.2f} (30=oversold, 70=overbought)
- MACD: {indicators['macd']:.4f} (positive=bullish, negative=bearish)
- Bollinger Bands Position: {indicators['price_to_bb']:.2f} (0=lower band, 1=upper band)
- Trend: {indicators['trend']}
- 24h Price Change: {market_data.get('price_change_24h', 0)}%

Market Context:
- Volume (24h): ${market_data.get('volume_24h', 'N/A')}
- Market Cap: ${market_data.get('market_cap', 'N/A')}

Based on technical analysis, provide your trading signal:
SIGNAL: [BUY/HOLD/SELL]
CONFIDENCE: [0-100]
REASONING: [Your technical analysis]"""

            response = await self.llm_client.ainvoke(
                [{"role": "user", "content": prompt}]
            )
            response_text = response.content
            
            # Parse response
            signal, confidence, reasoning = self._parse_llm_response(response_text)
            score = self._signal_to_score(signal)

            return AnalysisResult(
                analyst_type="technical",
                score=score,
                confidence=confidence / 100.0 if confidence else 0.5,
                reasoning=reasoning,
                key_metrics=key_metrics,
                timestamp=datetime.utcnow().isoformat(),
            )

        except Exception as e:
            logger.error(f"Technical analyst error: {e}")
            return AnalysisResult(
                analyst_type="technical",
                score=0.0,
                confidence=0.0,
                reasoning=f"Technical analysis error: {e}",
                key_metrics={"error": str(e)},
                timestamp=datetime.utcnow().isoformat(),
            )

    def _fetch_price_history(self, crypto_id: Optional[str]) -> list:
        """Fetch recent daily closing prices for indicator calculation

        Args:
            crypto_id: CoinGecko coin id (e.g. 'bitcoin')

        Returns:
            List of closing prices, oldest first (empty if unavailable)
        """
        if not crypto_id or not self.coingecko_api:
            return []
        try:
            historical = self.coingecko_api.get_historical_data(crypto_id, days=30)
            return [point[1] for point in historical.get("prices", [])]
        except Exception as e:
            logger.warning(f"Could not fetch historical prices for {crypto_id}: {e}")
            return []

    def _calculate_indicators(self, price: float, symbol: str, prices: Optional[list] = None) -> dict:
        """Calculate technical indicators from real historical prices

        Args:
            price: Current price
            symbol: Crypto symbol
            prices: Historical closing prices (oldest first)

        Returns:
            Dict of indicator values
        """
        # MACD needs 26 points minimum; fall back to neutral if data is too thin
        if prices and len(prices) >= 26:
            return self._calculate_real_indicators(prices)

        logger.warning(f"Insufficient historical data for {symbol} ({len(prices) if prices else 0} points), using neutral indicators")
        return {"rsi": 50.0, "macd": 0.0, "price_to_bb": 0.5, "trend": "neutral"}

    def _calculate_real_indicators(self, prices: list) -> dict:
        """Compute RSI(14), MACD(12,26), Bollinger Band position, and trend from a price series"""
        series = pd.Series(prices, dtype=float)

        # RSI (14-period)
        delta = series.diff()
        gain = delta.clip(lower=0).rolling(window=14).mean()
        loss = (-delta.clip(upper=0)).rolling(window=14).mean()
        rs = gain / loss.replace(0, 1e-9)
        rsi_series = 100 - (100 / (1 + rs))
        rsi = float(rsi_series.iloc[-1]) if pd.notna(rsi_series.iloc[-1]) else 50.0

        # MACD (12-EMA minus 26-EMA)
        ema12 = series.ewm(span=12, adjust=False).mean()
        ema26 = series.ewm(span=26, adjust=False).mean()
        macd = float((ema12 - ema26).iloc[-1])

        # Bollinger Bands (20-period, 2 std dev) - position of price within the band, 0-1
        window = min(20, len(series))
        rolling_mean = series.rolling(window=window).mean()
        rolling_std = series.rolling(window=window).std()
        upper_band = (rolling_mean + 2 * rolling_std).iloc[-1]
        lower_band = (rolling_mean - 2 * rolling_std).iloc[-1]
        band_width = upper_band - lower_band
        if band_width and pd.notna(band_width):
            price_to_bb = max(0.0, min(1.0, (series.iloc[-1] - lower_band) / band_width))
        else:
            price_to_bb = 0.5

        # Trend from short vs long moving average
        sma_short = series.tail(10).mean()
        sma_long = series.tail(min(30, len(series))).mean()
        if sma_short > sma_long * 1.01:
            trend = "uptrend"
        elif sma_short < sma_long * 0.99:
            trend = "downtrend"
        else:
            trend = "neutral"

        return {"rsi": rsi, "macd": macd, "price_to_bb": float(price_to_bb), "trend": trend}

    def _generate_reasoning(
        self,
        symbol: str,
        indicators: dict,
        metrics: dict,
        score: float
    ) -> str:
        """Generate reasoning for technical analysis"""
        trend = indicators.get("trend", "unknown")
        rsi = indicators.get("rsi", 0)
        rsi_signal = metrics.get("rsi_signal", "unknown")
        macd_signal = metrics.get("macd_signal", "unknown")

        return (
            f"Technical analysis for {symbol}: Current trend is {trend}. "
            f"RSI ({rsi}) indicates {rsi_signal}. "
            f"MACD is {macd_signal}. "
            f"Price action suggests a {score:.1%} bullish bias."
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

    def _create_no_data_result(self) -> AnalysisResult:
        """Create result when data unavailable"""
        return AnalysisResult(
            analyst_type="technical",
            score=0.0,
            confidence=0.0,
            reasoning="Insufficient price data for technical analysis",
            key_metrics={},
            timestamp=datetime.utcnow().isoformat(),
        )
