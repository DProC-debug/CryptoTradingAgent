# CryptoTradingAgents

An autonomous, multi-agent LLM crypto trading bot that trades Hyperliquid perpetuals, driven end-to-end by **Nansen on-chain and Smart Money data** — from picking which coins to look at, to how it scores them, to a live 3D dashboard of the agents themselves.

Eight specialized agents (five analysts, a bull/bear debate, a trader, a risk manager, and a portfolio manager) run every trading cycle, backed by real safety controls: a daily-loss circuit breaker, correlation-aware position limits, crash-safe state, and a memory system that feeds a coin's own recent stop-loss/liquidation history back into its next analysis.

**Status**: 🏗️ Active development — built for the Nansen buildathon.

## What makes this a Nansen project

Nansen data is load-bearing at three separate points in the pipeline, not just a side panel:

1. **Coin selection** (`cryptoagents/utilities/coin_selector.py`) — instead of picking random/liquidity-weighted altcoins each cycle, it can rank candidates by Nansen **Smart Money net accumulation** over a configurable window (`HYPERLIQUID_COIN_SELECTION_WEIGHT=smart_money`), filtering out flows backed by too few distinct wallets (`HYPERLIQUID_SMART_MONEY_MIN_TRADERS`) to avoid single-whale noise. Falls back to liquidity weighting automatically if Nansen has no signal for the batch.
2. **On-chain analysis** (`cryptoagents/agents/blockchain_analyst.py`) — combines Nansen's Hyperliquid perp positioning data (Smart Money long/short ratio) with real on-chain spot exchange/whale/smart-trader net flow for the same token, and **deterministically flags spot/perp divergence** (e.g. Smart Money net long on leveraged derivatives while the same cohort is distributing on spot) as an explicit caution signal the LLM can't average away.
3. **Live execution** (`cryptoagents/exchanges/nansen_perp_trader.py`) — the default trading backend routes Hyperliquid perp order placement through Nansen's perp API rather than the raw Hyperliquid SDK.

## Architecture

```
                    ┌──────────────────────┐
                    │  Portfolio Manager    │   final approval, holdings/rebalancing
                    └──────────┬────────────┘
                               │
                    ┌──────────▼────────────┐
                    │     Risk Manager       │   position-size adjustment, loss caps
                    └──────────┬────────────┘
                               │
                    ┌──────────▼────────────┐
                    │      Trader Agent      │   BUY / SELL / HOLD + confidence
                    └──────────┬────────────┘
                               │
                    ┌──────────▼────────────┐
                    │  Researcher Debate     │   bullish vs bearish synthesis
                    │     (bull vs bear)     │
                    └──────────┬────────────┘
                               │
        ┌───────────┬─────────┼─────────┬───────────┐
        │           │         │         │           │
   Blockchain   Sentiment  Technical   Macro   Fundamental
    Analyst      Analyst    Analyst   Analyst    Analyst
   (Nansen +               (RSI/MACD/  (BTC       (supply,
    on-chain)               Bollinger) dominance)  dilution)
```

`cryptoagents/graph/trading_graph.py` (`CryptoTradingGraph`) orchestrates all of this per symbol via `propagate()`. `cryptoagents/autonomous_trading_loop.py` (`AutonomousTrader`) is what actually runs it continuously: selecting a batch of coins, calling `propagate()` on each, sizing and placing orders, and monitoring open positions for take-profit/stop-loss.

### Safety and effectiveness controls

- **Daily loss circuit breaker** — halts new entries once today's account balance drops more than `HYPERLIQUID_MAX_DAILY_LOSS_PCT` below the day's starting balance (existing positions still get monitored/closed normally).
- **Category correlation limits** — caps concurrent positions sharing a CoinGecko sector tag (e.g. "Meme", "DeFi") as a proxy for correlation, since real historical correlation data isn't available for arbitrary altcoins.
- **Leveraged-ROE take-profit/stop-loss** — `HYPERLIQUID_TAKE_PROFIT_PCT` / `HYPERLIQUID_STOP_LOSS_PCT` are measured against a position's actual ROE (so the threshold scales correctly with whatever leverage confidence-scaling picked for that trade), checked every `HYPERLIQUID_MONITORING_INTERVAL_SECONDS`.
- **Liquidation detection** — since Hyperliquid can liquidate a position between our polling intervals, `monitor_positions()` diffs each cycle's open positions against what we expect to still be open and flags anything that vanished on its own as liquidated.
- **Trade-history memory** (`cryptoagents/utilities/trade_history.py`) — every stop-loss or liquidation is logged with a timestamp, independent of the daily/restart-scoped trade log. If the same coin comes up for analysis again within 24 hours, every analyst's prompt gets an explicit note about that recent loss.
- **Automatic stablecoin filtering** — excludes anything trading within a small band of $1 regardless of ticker, catching stablecoins a fixed exclude-list wouldn't know by name.
- **Crash-safe state** — today's trade log, starting balance baseline, and cycle count are persisted atomically and restored on restart.

## Web dashboard

`web/meeting-room.html` is a 3D dashboard of the agent team, backed by live data from your trading account. It's a Three.js conference room where all eight agents (Ledger, Mood, Chart, Compass, Sage, Ace, Warden, Figs — mapped respectively to the on-chain, sentiment, technical, macro, fundamental, trader, risk-manager, and portfolio-manager roles above) sit around a table, each playing their own animation. Clicking a character opens a popup built from the current account snapshot:

| Agent | Popup shows |
| --- | --- |
| **Figs** (Portfolio Manager) | Total balance, free collateral, open positions |
| **Ace** (Trader) | Total collateral, unrealized P&L, funding paid, and a per-position table (entry, mark, leverage, funding, P&L) |
| **Chart** (Technical Analyst) | Recent BUY/SELL/HOLD signals with confidence and score |
| **Mood** (Sentiment Analyst) | Buy/sell/hold breakdown and overall lean |
| **Compass** (Macro Analyst) | Long vs. short notional exposure |
| **Sage** (Fundamental Analyst) | Cycle count, today's trades, aggregate P&L and funding |
| **Warden** (Risk Manager) | Your configured risk limits (read from `.env` into each snapshot) vs. current usage of the daily loss budget |
| **Ledger** (On-Chain Analyst) | Net and per-position funding paid |

### How the live data works

`web/server.py` runs the dashboard locally with no extra dependencies. It serves the page plus a `/api/state` endpoint, and a background thread rebuilds the snapshot (`web/export_state.py`) from three real sources: your live Hyperliquid account (balance and open positions, through the same trader client the bot uses), the bot's persisted state file (today's trades, cycle count), and the tail of `autonomous_trader.log` (recent verdicts). Popups read `/api/state` when opened.

- **Refresh cadence:** every `DASHBOARD_REFRESH_MINUTES` (default 5) while the page's **Start Agents** button is on. Pressing it captures a fresh snapshot immediately, then continues on the interval until you press it again. This is a periodic snapshot, not a streaming feed — each popup shows its "as of" timestamp.
- **Read-only:** the button only controls the dashboard's data refresh. It never starts, stops, or places orders for the trading bot, which runs as its own process.
- **Resilient:** if a refresh fails (exchange or network error), the last good snapshot keeps being served and the error is reported at `/api/loop`.
- **Local only:** the server binds to `127.0.0.1` and rejects non-local Host headers, since the endpoint exposes live account data.

```bash
python web/server.py --open      # then press Start Agents on the page
```

The 3D models and background music aren't in the repo (they're large source assets); the server serves them from `web/models/*.js` and `web/audio/`, which you generate from your own `.glb` files with `web/animation/embed_gltf.py`. The same page can also be published as a Claude Artifact, where it reads a snapshot stored in the artifact's database instead of `/api/state` — there the data is only as fresh as the last snapshot pushed into it, since a published page can't reach your machine.

## Project structure

```
CryptoTradingAgents/
├── cryptoagents/
│   ├── agents/
│   │   ├── base_analyst.py           # Shared analyst interface
│   │   ├── blockchain_analyst.py     # Nansen perp positioning + on-chain flow
│   │   ├── sentiment_analyst.py      # Market sentiment (LLM-driven)
│   │   ├── technical_analyst.py      # RSI/MACD/Bollinger Bands from real price history
│   │   ├── macro_analyst.py          # BTC dominance, market cycle
│   │   ├── fundamental_analyst.py    # Supply/dilution, community signals
│   │   ├── researcher.py             # Bull vs bear debate synthesis
│   │   ├── trader.py                 # Final BUY/SELL/HOLD decision
│   │   ├── risk_manager.py           # Position-size adjustment, risk metrics
│   │   └── portfolio_manager.py      # Holdings, rebalancing recommendations
│   ├── dataflows/
│   │   ├── nansen_api.py             # Smart Money netflow, on-chain flow intelligence
│   │   └── coingecko_api.py          # Market data, historical prices, coin resolution
│   ├── exchanges/
│   │   ├── hyperliquid_trader.py     # Direct Hyperliquid SDK execution
│   │   └── nansen_perp_trader.py     # Nansen-routed Hyperliquid perp execution (default)
│   ├── graph/
│   │   └── trading_graph.py          # CryptoTradingGraph - orchestrates one full analysis
│   ├── utilities/
│   │   ├── coin_selector.py          # Random/liquidity/Smart-Money-weighted coin selection
│   │   └── trade_history.py          # Persistent loss/liquidation memory
│   ├── backtesting/
│   │   ├── backtest_engine.py        # Runs the real multi-agent pipeline over real history
│   │   └── historical_data.py        # Real historical price fetching
│   └── autonomous_trading_loop.py    # AutonomousTrader - the live/simulated trading loop
├── cli/
│   ├── main.py                       # Typer CLI (analyze / market / config / test)
│   └── autonomous_trader.py          # Entry point for the continuous autonomous loop
├── web/
│   ├── meeting-room.html             # 3D agent dashboard (Three.js)
│   ├── server.py                     # Local server: serves the page + /api/state, refreshes every 5 min
│   ├── export_state.py               # Builds a live balance/positions/verdicts snapshot
│   └── animation/embed_gltf.py       # Packs a .gltf + textures into one self-contained file
├── backtest_cli.py                   # Simple single-symbol backtest
├── backtest_advanced.py              # Multi-symbol backtest with more reporting
├── main.py                           # Quick-start script (analyzes BTC once)
├── .env.example                      # Full list of configuration variables
└── pyproject.toml
```

## Setup

### 1. Install

```bash
git clone https://github.com/DProC-debug/CryptoTradingAgent.git
cd CryptoTradingAgent
pip install -e .
```

### 2. Configure

```bash
cp .env.example .env
```

At minimum, set:
- `OPENROUTER_API_KEY` — LLM access (Claude, GPT-4o, DeepSeek, etc. via OpenRouter)
- `NANSEN_API_KEY` — Smart Money netflow, on-chain flow, and (if `TRADING_BACKEND=nansen`) perp execution
- `COINGECKO_API_KEY` — optional, raises rate limits

To place real orders, also set `PORTFOLIO_WALLET_HYPERLIQUID`, `PORTFOLIO_WALLET_PRIVATE_KEY`, and `HYPERLIQUID_TRADING_ENABLED=true`. See `.env.example` for the full set of trading/risk parameters (position sizing, leverage, take-profit/stop-loss, daily loss limit, category limits, coins per cycle, and the Smart Money selection settings) — every one of them is tunable without touching code.

### 3. Run

```bash
# One-off analysis of a single coin
cryptoagents analyze BTC --timeframe 1h

# Backtest against real historical data
python backtest_cli.py --symbol BTC --days 90

# Run the autonomous loop continuously (paper-trades unless HYPERLIQUID_TRADING_ENABLED=true)
python cli/autonomous_trader.py

# Local 3D dashboard (refreshes its data every 5 minutes once you press Start Agents)
python web/server.py --open
```

## Trading Disclaimer

⚠️ **This is research software, not financial advice.** Live trading uses real funds and leverage; LLM outputs are non-deterministic and market conditions change. Test with `HYPERLIQUID_TRADING_ENABLED=false` (paper mode) before enabling real orders, and never risk more than you can afford to lose.

## License

MIT License — see [LICENSE](./LICENSE).
