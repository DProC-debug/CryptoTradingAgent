"""Main trading graph orchestration engine for CryptoTradingAgents"""

import logging
import os
import asyncio
from datetime import datetime
from typing import Any, Optional
from dotenv import load_dotenv

from cryptoagents.dataflows import CoinGeckoAPI, NansenAPI
from cryptoagents.default_config import DEFAULT_CONFIG
from cryptoagents.llm_clients import create_llm_client
from cryptoagents.agents import (
    BlockchainAnalyst,
    SentimentAnalyst,
    TechnicalAnalyst,
    MacroAnalyst,
    FundamentalAnalyst,
    ResearcherDebate,
    TraderAgent,
    RiskManager,
    PortfolioManager,
)

logger = logging.getLogger(__name__)


class CryptoTradingGraph:
    """Main orchestration engine for crypto trading agents"""

    def __init__(
        self,
        config: Optional[dict[str, Any]] = None,
        debug: bool = False,
        hyperliquid_trader: Optional[Any] = None,
    ):
        """Initialize the crypto trading graph

        Args:
            config: Configuration dictionary. If None, uses DEFAULT_CONFIG
            debug: Whether to run in debug mode
            hyperliquid_trader: Optional live HyperliquidTrader for real portfolio data
        """
        self.debug = debug
        self.config = config or DEFAULT_CONFIG.copy()

        logger.info(f"Initializing CryptoTradingGraph (debug={debug})")

        # Create necessary directories
        os.makedirs(self.config["data_cache_dir"], exist_ok=True)
        os.makedirs(self.config["results_dir"], exist_ok=True)

        # Initialize LLM clients
        try:
            self.deep_llm = create_llm_client(
                provider=self.config["llm_provider"],
                model=self.config["deep_think_llm"],
                api_key=self.config.get("openrouter_api_key"),
                temperature=self.config.get("temperature"),
                max_tokens=self.config.get("max_tokens"),
                base_url=self.config.get("ollama_base_url"),
            ).get_llm()
            logger.info(
                f"[OK] Deep thinking LLM initialized: {self.config['deep_think_llm']}"
            )
        except Exception as e:
            logger.error(f"Failed to initialize deep LLM: {e}")
            raise

        try:
            self.quick_llm = create_llm_client(
                provider=self.config["llm_provider"],
                model=self.config["quick_think_llm"],
                api_key=self.config.get("openrouter_api_key"),
                temperature=self.config.get("temperature"),
                max_tokens=self.config.get("max_tokens"),
                base_url=self.config.get("ollama_base_url"),
            ).get_llm()
            logger.info(
                f"[OK] Quick thinking LLM initialized: {self.config['quick_think_llm']}"
            )
        except Exception as e:
            logger.error(f"Failed to initialize quick LLM: {e}")
            raise

        # Initialize data APIs
        try:
            self.nansen = NansenAPI(self.config.get("nansen_api_key", ""))
            if self.nansen.health_check():
                logger.info("[OK] Nansen API connected")
            else:
                logger.warning("⚠ Nansen API health check failed")
        except Exception as e:
            logger.warning(f"Nansen API initialization failed: {e}")
            self.nansen = None

        try:
            self.coingecko = CoinGeckoAPI(self.config.get("coingecko_api_key"))
            if self.coingecko.health_check():
                logger.info("[OK] CoinGecko API connected")
            else:
                logger.warning("⚠ CoinGecko API health check failed")
        except Exception as e:
            logger.error(f"CoinGecko API initialization failed: {e}")
            raise

        # Initialize specialized analysts
        self.blockchain_analyst = BlockchainAnalyst(self.nansen, coingecko_api=self.coingecko, llm_client=self.deep_llm)
        self.sentiment_analyst = SentimentAnalyst(self.deep_llm)
        self.technical_analyst = TechnicalAnalyst(self.coingecko, self.quick_llm)
        self.macro_analyst = MacroAnalyst(self.coingecko, self.deep_llm)
        self.fundamental_analyst = FundamentalAnalyst(self.coingecko, self.deep_llm)

        # Initialize researcher debate, trader, and portfolio manager
        self.debate_system = ResearcherDebate(self.deep_llm)
        self.trader = TraderAgent(self.deep_llm)
        self.risk_manager = RiskManager(
            portfolio_value=self.config.get("initial_portfolio_value", 100000.0),
            llm_client=self.deep_llm
        )
        
        # Load wallet addresses from environment
        load_dotenv()
        wallet_addresses = {
            "hyperliquid": os.getenv("PORTFOLIO_WALLET_HYPERLIQUID", ""),
            "solana": os.getenv("PORTFOLIO_WALLET_SOLANA", ""),
        }
        stable_coin_reserve = float(os.getenv("PORTFOLIO_STABLE_COIN_RESERVE", "0.30"))
        max_allocation = float(os.getenv("PORTFOLIO_MAX_ALLOCATION_PER_ASSET", "0.15"))
        
        self.portfolio_manager = PortfolioManager(
            nansen_api=self.nansen,
            coingecko_api=self.coingecko,
            wallet_addresses=wallet_addresses,
            stable_coin_reserve=stable_coin_reserve,
            max_allocation_per_asset=max_allocation,
            portfolio_value=self.config.get("initial_portfolio_value", 100000.0),
            hyperliquid_trader=hyperliquid_trader,
        )

        logger.info("[OK] All analysts initialized")
        logger.info("[OK] Debate system initialized")
        logger.info("[OK] Trader agent initialized")
        logger.info("[OK] Risk manager initialized")
        logger.info("[OK] Portfolio manager initialized")
        logger.info("CryptoTradingGraph initialized successfully")

    async def analyze(self, crypto_symbol: str, timeframe: str = "1h") -> dict:
        """Run full analysis pipeline for a cryptocurrency

        Args:
            crypto_symbol: Cryptocurrency symbol (e.g., 'BTC', 'ETH')
            timeframe: Analysis timeframe

        Returns:
            Analysis results dictionary
        """
        logger.info(f"Starting analysis for {crypto_symbol} ({timeframe})")

        analysis_result = {
            "timestamp": datetime.now().isoformat(),
            "crypto": crypto_symbol,
            "timeframe": timeframe,
            "status": "pending",
            "error": None,
            "analyses": {},
        }

        try:
            # Fetch market data
            market_data = self.coingecko.get_crypto_by_symbol(crypto_symbol)
            if not market_data:
                raise ValueError(f"Could not fetch market data for {crypto_symbol}")

            analysis_result["market_data"] = market_data

            # Run all analysts concurrently
            results = await self._run_all_analysts(crypto_symbol, market_data)
            analysis_result["analyses"] = results

            # Synthesize analyst results
            synthesized = self._synthesize_analyses(results)
            analysis_result["synthesized_signal"] = synthesized

            # Run researcher debate
            debate_result = self.debate_system.debate(
                crypto_symbol,
                results,
                market_data,
            )
            analysis_result["debate_result"] = {
                "winner": debate_result.winner,
                "consensus_score": debate_result.consensus_score,
                "bullish_arguments": len(debate_result.bullish_arguments),
                "bearish_arguments": len(debate_result.bearish_arguments),
                "reasoning": debate_result.debate_reasoning,
            }
            logger.info(f"Debate complete: {debate_result.winner.upper()} researcher prevails")

            # Trader makes final decision
            trade_decision = self.trader.decide(
                crypto_symbol,
                market_data,
                synthesized["overall_score"],
                debate_result,
                results,
            )
            analysis_result["trade_decision"] = {
                "signal": trade_decision.signal,
                "position_size": trade_decision.position_size,
                "confidence": trade_decision.confidence,
                "entry_price": trade_decision.entry_price,
                "stop_loss": trade_decision.stop_loss,
                "take_profit": trade_decision.take_profit,
                "risk_reward_ratio": trade_decision.risk_reward_ratio,
                "reasoning": trade_decision.reasoning,
            }
            logger.info(f"Trading decision: {trade_decision.signal} (confidence: {trade_decision.confidence:.2%})")

            # Risk manager assesses the trade
            risk_metrics = self.risk_manager.assess_trade_risk(
                trade_decision,
                market_data,
            )
            analysis_result["risk_metrics"] = {
                "adjusted_position_size": risk_metrics.adjusted_position_size,
                "max_portfolio_loss": risk_metrics.max_portfolio_loss,
                "loss_percentage": risk_metrics.loss_percentage,
                "gain_percentage": risk_metrics.gain_percentage,
                "risk_reward_ratio": risk_metrics.risk_reward_ratio,
                "reasoning": risk_metrics.reasoning,
            }
            logger.info(f"Risk assessment: Position adjusted to {risk_metrics.adjusted_position_size:.0%} (max loss: {risk_metrics.max_portfolio_loss:.2%})")

            # Portfolio manager analyzes current holdings and makes rebalancing recommendations
            portfolio_state = self.portfolio_manager.fetch_holdings()
            portfolio_metrics = self.portfolio_manager.calculate_portfolio_metrics()
            
            # Create trade decisions dict for portfolio manager
            trade_decisions_for_portfolio = {
                crypto_symbol: (
                    trade_decision.signal,
                    trade_decision.confidence,
                    synthesized["overall_score"]
                )
            }
            
            rebalance_recommendations = self.portfolio_manager.make_rebalance_recommendations(
                trade_decisions_for_portfolio
            )
            
            analysis_result["portfolio"] = {
                "total_value": portfolio_state.total_value_usd,
                "stablecoin_reserve": portfolio_state.stablecoin_percentage,
                "cash_available": portfolio_state.cash_available,
                "num_holdings": len(portfolio_state.holdings),
                "diversification_score": portfolio_metrics.get("diversification_score", 0),
                "largest_position": portfolio_metrics.get("largest_position", 0),
                "rebalance_actions": [
                    {
                        "symbol": rec.symbol,
                        "action": rec.action,
                        "amount_usd": rec.amount_usd,
                        "amount_tokens": rec.amount_tokens,
                        "urgency": rec.urgency,
                        "reasoning": rec.reasoning,
                    }
                    for rec in rebalance_recommendations if rec.requires_action
                ],
            }
            logger.info(f"Portfolio: ${portfolio_state.total_value_usd:,.0f} ({len(portfolio_state.holdings)} holdings, {portfolio_state.stablecoin_percentage:.0%} stables)")

            analysis_result["status"] = "completed"
            logger.info(f"Analysis completed for {crypto_symbol}")

        except Exception as e:
            logger.error(f"Analysis failed: {e}")
            analysis_result["status"] = "failed"
            analysis_result["error"] = str(e)

        return analysis_result

    async def _run_all_analysts(self, crypto_symbol: str, market_data: dict) -> dict:
        """Run all analyst agents concurrently

        Args:
            crypto_symbol: Cryptocurrency symbol
            market_data: Market data from CoinGecko

        Returns:
            Dict with all analyst results
        """
        tasks = [
            self.blockchain_analyst.analyze(crypto_symbol, market_data),
            self.sentiment_analyst.analyze(crypto_symbol, market_data),
            self.technical_analyst.analyze(crypto_symbol, market_data),
            self.macro_analyst.analyze(crypto_symbol, market_data),
            self.fundamental_analyst.analyze(crypto_symbol, market_data),
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        return {
            "blockchain": results[0] if not isinstance(results[0], Exception) else None,
            "sentiment": results[1] if not isinstance(results[1], Exception) else None,
            "technical": results[2] if not isinstance(results[2], Exception) else None,
            "macro": results[3] if not isinstance(results[3], Exception) else None,
            "fundamental": results[4] if not isinstance(results[4], Exception) else None,
        }

    def _synthesize_analyses(self, analyses: dict) -> dict:
        """Synthesize results from all analysts

        Args:
            analyses: Dict with results from all analysts

        Returns:
            Synthesized decision
        """
        scores = []
        confidences = []
        reasoning_points = []

        for analyst_name, result in analyses.items():
            if result and hasattr(result, 'score'):
                scores.append(result.score)
                confidences.append(result.confidence)
                reasoning_points.append(
                    f"{analyst_name}: {result.reasoning}"
                )

        logger.info(
            "[ANALYST SCORES] " + ", ".join(
                f"{name}=score:{r.score:.2f}/conf:{r.confidence:.2f}"
                for name, r in analyses.items() if r and hasattr(r, 'score')
            )
        )

        if not scores:
            return {
                "signal": "HOLD",
                "overall_score": 0.0,
                "confidence": 0.0,
                "reasoning": "Unable to synthesize analysis",
            }

        # Calculate average score and confidence
        avg_score = sum(scores) / len(scores)
        avg_confidence = sum(confidences) / len(confidences)

        # Determine signal (RELAXED thresholds for more frequent trading)
        if avg_score > 0.0:   # Lowered from 0.15 - now ANY positive sentiment triggers BUY
            signal = "BUY"
        elif avg_score < 0.0:  # Lowered from -0.15 - any negative triggers SELL
            signal = "SELL"
        else:
            signal = "HOLD"

        return {
            "signal": signal,
            "overall_score": avg_score,
            "confidence": avg_confidence,
            "reasoning": " | ".join(reasoning_points),
        }

    def get_market_overview(self) -> dict:
        """Get overview of cryptocurrency market"""
        logger.info("Fetching market overview")

        try:
            global_data = self.coingecko.get_global_data()
            market_data = self.coingecko.get_market_data(per_page=10)

            return {
                "timestamp": datetime.now().isoformat(),
                "global": global_data,
                "top_10": market_data,
            }
        except Exception as e:
            logger.error(f"Failed to fetch market overview: {e}")
            return {}

    async def propagate(self, crypto_symbol: str, date: str) -> tuple[bool, dict]:
        """Main propagation method - full trading pipeline

        Args:
            crypto_symbol: Cryptocurrency symbol
            date: Analysis date

        Returns:
            Tuple of (success, decision_dict)
        """
        logger.info(f"Propagating analysis for {crypto_symbol} on {date}")

        try:
            result = await self.analyze(crypto_symbol)
            
            # Extract trader decision and risk metrics from analysis
            trade_decision = result.get("trade_decision", {})
            risk_metrics = result.get("risk_metrics", {})
            
            decision = {
                "timestamp": datetime.now().isoformat(),
                "crypto": crypto_symbol,
                "date": date,
                "signal": trade_decision.get("signal", "HOLD"),
                "confidence": trade_decision.get("confidence", 0.0),
                "reasoning": trade_decision.get("reasoning", "Analysis pending"),
                "position_size": risk_metrics.get("adjusted_position_size", trade_decision.get("position_size", 0.0)),
                "max_portfolio_loss": risk_metrics.get("max_portfolio_loss", 0.0),
                "loss_percentage": risk_metrics.get("loss_percentage"),
                "gain_percentage": risk_metrics.get("gain_percentage"),
                "risk_reward_ratio": trade_decision.get("risk_reward_ratio", 0.0),
                "analysis": result,
            }

            return True, decision

        except Exception as e:
            logger.error(f"Propagation failed: {e}")
            return False, {"error": str(e)}
