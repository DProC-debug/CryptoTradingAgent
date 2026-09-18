"""Blockchain Analyst - On-chain metrics and whale movement analysis"""

import logging
from datetime import datetime
from typing import Optional
from .base_analyst import BaseAnalyst, AnalysisResult

logger = logging.getLogger(__name__)


class BlockchainAnalyst(BaseAnalyst):
    """Analyzes Hyperliquid perp positioning by trader cohort (Smart Money, Whales, Public Figures) using Nansen"""

    # Spot/perp divergence check (see analyze()): minimum magnitude on each side before a
    # sign disagreement counts as a real signal rather than noise around zero
    DIVERGENCE_MIN_PERP_RATIO = 0.2  # |smart_money_net_ratio| - a real directional lean, not a coin flip
    DIVERGENCE_MIN_SPOT_FLOW_USD = 10_000  # |smart_trader_net_flow_usd| - real flow, not dust
    DIVERGENCE_CONFIDENCE_CAP = 40  # confidence ceiling (0-100) when a divergence is detected

    def __init__(self, nansen_api, coingecko_api=None, llm_client=None):
        """Initialize blockchain analyst

        Args:
            nansen_api: NansenAPI instance
            coingecko_api: Optional CoinGeckoAPI instance, used to resolve a symbol to an
                on-chain (chain, contract_address) pair so real spot exchange/whale/smart-
                trader flow can be fetched alongside Hyperliquid perp positioning. Flow
                enrichment is skipped (not an error) if this isn't provided.
            llm_client: LLM client for deep reasoning
        """
        super().__init__("blockchain", llm_client)
        self.nansen = nansen_api
        self.coingecko_api = coingecko_api

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
            has_positioning = bool(positioning) and any(positioning.values())

            # On-chain spot flow (exchange/whale/smart-trader/fresh-wallet), distinct from
            # the derivatives positioning above - needs a real contract address, so it's
            # only available when CoinGecko can resolve one on a Nansen-supported chain
            # (native L1s like TIA/ZEC won't resolve; that's expected, not an error)
            flow = {}
            flow_chain = None
            if self.coingecko_api:
                resolved = self.coingecko_api.resolve_chain_and_address(crypto_symbol)
                if resolved:
                    flow_chain, address = resolved
                    flow = self.nansen.get_token_flow_intelligence(flow_chain, address, timeframe="1d")

            if not has_positioning and not flow:
                return self._create_no_data_result()

            key_metrics = {}
            smart_money_ratio = 0.0
            positioning_section = "Hyperliquid derivatives positioning data unavailable for this token.\n"

            if has_positioning:
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

                key_metrics.update({
                    "smart_money_net_ratio": smart_money_ratio,
                    "smart_money_longs_usd": smart_longs,
                    "smart_money_shorts_usd": smart_shorts,
                    "whale_net_ratio": whale_ratio,
                    "whale_longs_usd": whale_longs,
                    "whale_shorts_usd": whale_shorts,
                    "public_figure_net_ratio": public_figure_ratio,
                })

                positioning_section = f"""Positioning by Trader Cohort (net long/short USD exposure, -1.0 = fully short, +1.0 = fully long):
- Smart Money: {smart_money_ratio:+.2f} (${smart_longs:,.0f} long vs ${smart_shorts:,.0f} short)
- Whales: {whale_ratio:+.2f} (${whale_longs:,.0f} long vs ${whale_shorts:,.0f} short)
- Public Figures: {public_figure_ratio:+.2f} (${public_longs:,.0f} long vs ${public_shorts:,.0f} short)
"""

            flow_section = "On-chain spot flow data unavailable for this token.\n"
            if flow:
                exchange_flow = flow.get("exchange_net_flow_usd", 0)
                whale_flow = flow.get("whale_net_flow_usd", 0)
                smart_trader_flow = flow.get("smart_trader_net_flow_usd", 0)
                fresh_wallet_flow = flow.get("fresh_wallets_net_flow_usd", 0)

                key_metrics.update({
                    "exchange_net_flow_usd": exchange_flow,
                    "onchain_whale_net_flow_usd": whale_flow,
                    "onchain_smart_trader_net_flow_usd": smart_trader_flow,
                    "fresh_wallets_net_flow_usd": fresh_wallet_flow,
                })

                flow_section = f"""On-Chain Spot Flow (24h, {flow_chain}):
- Exchange Net Flow: ${exchange_flow:,.0f} (positive = inflow to exchanges, often precedes selling; negative = outflow, often accumulation/cold storage)
- Whale Net Flow: ${whale_flow:,.0f}
- Smart Trader Net Flow: ${smart_trader_flow:,.0f}
- Fresh Wallet Net Flow: ${fresh_wallet_flow:,.0f}
"""

            # Spot/perp divergence: Smart Money leaning one way on Hyperliquid derivatives
            # while the same cohort's real spot flow moves the opposite way is a genuine
            # caution signal (a leveraged bet contradicted by real supply movement) - detected
            # deterministically here rather than left entirely to the LLM to notice and weigh
            divergence = False
            if has_positioning and flow:
                spot_flow = flow.get("smart_trader_net_flow_usd", 0)
                if (
                    abs(smart_money_ratio) >= self.DIVERGENCE_MIN_PERP_RATIO
                    and abs(spot_flow) >= self.DIVERGENCE_MIN_SPOT_FLOW_USD
                    and (smart_money_ratio > 0) != (spot_flow > 0)
                ):
                    divergence = True

            key_metrics["spot_perp_divergence"] = divergence
            divergence_warning = ""
            if divergence:
                divergence_warning = (
                    f"\nCAUTION: Smart Money is {'net long' if smart_money_ratio > 0 else 'net short'} on "
                    f"Hyperliquid derivatives but net {'buying' if spot_flow > 0 else 'selling'} on spot - "
                    f"this is a genuine divergence between a leveraged bet and real spot supply movement, "
                    f"not something to average away. Cap your confidence accordingly.\n"
                )

            # Use LLM for intelligent analysis
            if not self.llm_client:
                logger.warning("No LLM client available, using fallback")
                return self._create_no_data_result()

            history_note = ""
            if additional_context and additional_context.get("recent_loss_note"):
                history_note = additional_context["recent_loss_note"] + "\n"

            prompt = f"""Analyze Hyperliquid perpetual positioning and on-chain spot flow for {crypto_symbol} and provide a trading signal.

{history_note}{positioning_section}
{flow_section}
{divergence_warning}
Market Data:
- Current Price: ${market_data.get('current_price', market_data.get('usd', 'N/A'))}
- 24h Volume: ${market_data.get('volume_24h', 'N/A')}
- 24h Change: {market_data.get('price_change_24h', 'N/A')}%

Weigh Smart Money signals most heavily - historically the most predictive cohort - whether from
derivatives positioning, on-chain flow, or both (use whichever data is available above).
Derivatives positioning is a leveraged bet; on-chain flow is real spot supply moving - treat
disagreement between the two (e.g. long positioning while smart money distributes on-chain) as
a caution signal, not something to average away.
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

            # Hard-enforce the divergence cap rather than trusting the LLM to have applied
            # it - the prompt warning steers reasoning, but confidence must actually be capped
            if divergence and confidence > self.DIVERGENCE_CONFIDENCE_CAP:
                logger.info(
                    f"[DIVERGENCE] {crypto_symbol}: capping confidence {confidence} -> "
                    f"{self.DIVERGENCE_CONFIDENCE_CAP} (spot/perp disagreement)"
                )
                confidence = self.DIVERGENCE_CONFIDENCE_CAP
                reasoning = f"[Spot/perp divergence detected - confidence capped] {reasoning}"

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
        # Strip markdown formatting (**bold**, #headers, `code`) some models wrap labels in
        clean_response = re.sub(r"[*#`]", "", response)
        lines = clean_response.split('\n')
        signal = "HOLD"
        confidence = 50
        reasoning = response

        for line in lines:
            if "SIGNAL:" in line:
                token = line.split("SIGNAL:")[1].strip().split()[0] if line.split("SIGNAL:")[1].strip() else ""
                token = re.sub(r"[^A-Za-z]", "", token).upper()
                if token in ("BUY", "SELL", "HOLD"):
                    signal = token
            elif "CONFIDENCE:" in line:
                match = re.search(r"\d+", line.split("CONFIDENCE:")[1])
                if match:
                    confidence = int(match.group())

        # REASONING often spans multiple lines (label on its own line, content below it) -
        # take everything after the label in the full text, not just the label's own line,
        # or a "REASONING:\n<content>" response leaves reasoning empty
        if "REASONING:" in clean_response:
            reasoning = clean_response.split("REASONING:", 1)[1].strip()

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
