# CryptoTradingAgents 🚀

A sophisticated **multi-agent LLM-based cryptocurrency trading framework** powered by Nansen on-chain analytics and OpenRouter LLM APIs. This framework deploys specialized agents that collaborate to analyze markets, debate trading strategies, and execute decisions on a simulated exchange.

**Status**: 🏗️ In active development (v0.1.0)

## Features

- 🤖 **Multi-Agent Architecture**: Specialized agents for blockchain analysis, sentiment, technical analysis, macro trends, and fundamentals
- ⛓️ **Nansen Integration**: Real-time whale watching, smart money flows, and advanced on-chain metrics
- 🧠 **LLM-Powered Intelligence**: OpenRouter integration for access to Claude, GPT-4o, DeepSeek, and more
- 📊 **Technical Analysis**: Integrated TA-Lib indicators (RSI, MACD, Bollinger Bands, etc.)
- 🔄 **Debate Mechanism**: Bullish & bearish researchers dynamically challenge assumptions
- 💰 **Simulated Trading**: Full backtesting environment with realistic portfolio management
- 📈 **Learning & Reflection**: Trade memory system to improve decision-making over time
- 🔐 **Risk Management**: Portfolio-level risk assessment and position sizing
- 🌍 **Multi-Crypto Support**: Trade any cryptocurrency with available data

## Architecture

### Agent Hierarchy

```
┌─────────────────────────────────────────────┐
│         Portfolio Manager (Final Decision)  │
└────────────────┬────────────────────────────┘
                 │
         ┌───────┴────────┐
         │                │
    ┌────▼────┐    ┌─────▼─────┐
    │  Trader │    │Risk Manager│
    └────┬────┘    └─────┬─────┘
         │                │
    ┌────┴────────────────┘
    │
┌───▼──────────────────────────────────────┐
│    Researcher Debate (Bull vs Bear)      │
└───┬──────────────────────────────────────┘
    │
┌───▼──────────────────────────────────────┐
│          Analyst Team                     │
│  ┌──────────────────────────────────────┐ │
│  │ • Blockchain Analyst (Nansen)        │ │
│  │ • Sentiment Analyst (Social/News)    │ │
│  │ • Technical Analyst (Charts/Signals) │ │
│  │ • Macro Analyst (Market Dominance)   │ │
│  │ • Fundamental Analyst (Tokenomics)   │ │
│  └──────────────────────────────────────┘ │
└──────────────────────────────────────────┘
```

### Project Structure

```
CryptoTradingAgents/
├── cryptoagents/
│   ├── agents/
│   │   ├── analysts/
│   │   │   ├── blockchain_analyst.py     # Nansen on-chain data
│   │   │   ├── sentiment_analyst.py      # Social sentiment aggregation
│   │   │   ├── technical_analyst.py      # Chart patterns & indicators
│   │   │   ├── macro_analyst.py          # BTC dominance, market trends
│   │   │   └── fundamental_analyst.py    # Tokenomics, metrics
│   │   ├── researchers/
│   │   │   ├── bullish_researcher.py     # Pro-trade arguments
│   │   │   └── bearish_researcher.py     # Caution/risk arguments
│   │   ├── traders/
│   │   │   └── trader_agent.py           # Trading decisions
│   │   ├── managers/
│   │   │   ├── risk_manager.py           # Portfolio risk
│   │   │   └── portfolio_manager.py      # Final approval
│   │   └── utils/
│   │       ├── agent_utils.py            # Tool definitions
│   │       └── memory.py                 # Trade decision memory
│   ├── dataflows/
│   │   ├── nansen_api.py                 # Whale watching, smart money
│   │   ├── coingecko_api.py              # Market data, prices, volumes
│   │   ├── sentiment_feeds.py            # Twitter, Discord, Reddit
│   │   ├── technical_indicators.py       # TA-Lib indicators
│   │   ├── validators.py                 # Data validation
│   │   └── config.py                     # Dataflow config
│   ├── graph/
│   │   ├── trading_graph.py              # Main orchestration (LangGraph)
│   │   ├── propagation.py                # Data flow routing
│   │   ├── conditional_logic.py          # Decision paths
│   │   └── reflection.py                 # Learning from trades
│   ├── llm_clients/
│   │   └── openrouter_client.py          # OpenRouter integration
│   ├── simulated_exchange.py             # Backtest execution
│   ├── default_config.py                 # Configuration management
│   └── __init__.py
├── cli/
│   └── main.py                           # CLI entry point (Typer)
├── tests/
├── main.py                               # Quick start script
├── pyproject.toml                        # Dependencies & metadata
├── .env.example                          # Environment template
└── README.md                             # This file
```

## Quick Start

### 1. Installation

```bash
git clone https://github.com/YourUsername/CryptoTradingAgents.git
cd CryptoTradingAgents

# Create virtual environment
conda create -n cryptoagents python=3.12
conda activate cryptoagents

# Install dependencies
pip install -e .
```

### 2. Configuration

Copy and fill in your API keys:

```bash
cp .env.example .env
# Edit .env with your API keys:
# - OPENROUTER_API_KEY
# - NANSEN_API_KEY
# - COINGECKO_API_KEY (optional)
```

### 3. Run Analysis

```bash
# Quick start with Bitcoin
python main.py

# Or use CLI
cryptoagents analyze BTC --timeframe 1h --lookback 24h
cryptoagents backtest BTC,ETH --start 2024-01-01 --end 2024-12-31
cryptoagents trade BTC --live-mode  # Simulated exchange
```

## Required APIs

### OpenRouter (LLM Provider)
1. Go to [openrouter.ai](https://openrouter.ai)
2. Sign up and get API key
3. Set `OPENROUTER_API_KEY` in `.env`

**Recommended Models** (via OpenRouter):
- `claude-opus` - Deep analysis, reasoning
- `gpt-4o` - Fast data processing
- `deepseek-chat` - Cost-efficient backup

### Nansen (Blockchain Analytics)
1. Go to [nansen.ai](https://nansen.ai)
2. Create account and generate API key
3. Set `NANSEN_API_KEY` in `.env`

**Available Features**:
- Whale transactions & movements
- Smart money flows
- Token holder distributions
- On-chain volume metrics

### CoinGecko (Market Data - Free)
1. Go to [coingecko.com/api](https://www.coingecko.com/api)
2. Free tier available, optional API key for higher limits
3. Set `COINGECKO_API_KEY` in `.env` (optional)

## Agent Roles

### Blockchain Analyst
- Monitors on-chain metrics via Nansen
- Tracks whale movements and smart money
- Detects unusual transaction patterns
- Analyzes token holder concentration
- **Output**: On-chain sentiment score, risk flags

### Sentiment Analyst
- Aggregates social sentiment (Twitter, Discord, Reddit)
- Monitors news sentiment
- Tracks fear & greed index
- Detects coordinated trading signals
- **Output**: Sentiment score (-1 to +1), sentiment drivers

### Technical Analyst
- Analyzes price patterns (support, resistance, trends)
- Calculates indicators: RSI, MACD, Bollinger Bands, Moving Averages
- Detects breakout/breakdown signals
- Identifies chart formations
- **Output**: Technical score, trade signals, entry/exit levels

### Macro Analyst
- Monitors Bitcoin dominance
- Tracks altseason indicators
- Analyzes market cap trends
- Watches Fed policy, macro trends
- **Output**: Market bias (bullish/bearish), cycle phase

### Fundamental Analyst
- Evaluates token metrics (supply, circulation, unlock schedules)
- Analyzes project updates and roadmap
- Tracks exchange flows
- Monitors funding rounds
- **Output**: Fundamental score, valuation assessment

### Researchers (Bull & Bear)
- **Bullish Researcher**: Argues for buying, highlights upside catalysts
- **Bearish Researcher**: Challenges assumptions, highlights risks
- Debate mechanism: Iterative discussion to balance perspective
- **Output**: Weighted risk/reward assessment

### Trader Agent
- Synthesizes all analyst inputs
- Determines BUY/SELL/HOLD decisions
- Calculates position size and entry/exit levels
- Provides trading rationale
- **Output**: Trade signal with confidence score

### Risk Manager
- Evaluates portfolio concentration
- Assesses liquidity and slippage risk
- Calculates portfolio volatility
- Recommends position sizing
- **Output**: Risk assessment, position approval/rejection

### Portfolio Manager
- Final decision authority
- Approves/rejects trades
- Manages portfolio allocation
- Executes simulated orders
- **Output**: Execution status, portfolio state

## Data Flows

### Real-Time Monitoring
```
[Nansen] ─────┐
[CoinGecko] ──┼──> [Data Aggregator] ──> [Analysts] ──> [Traders] ──> [Execution]
[Sentiment] ──┘
```

### Analysis Flow
```
On-Chain Data ──> Blockchain Analyst ──┐
Social Data ──> Sentiment Analyst ──┬──> Researchers ──> Trader ──> Risk Manager ──> Portfolio Manager
Chart Data ──> Technical Analyst ───┤
Market Data ──> Macro Analyst ───────┘
Project Data ──> Fundamental Analyst ┘
```

## Configuration

All settings can be configured via `.env` variables (see `.env.example`):

```python
# LLM Configuration
CRYPTOAGENTS_LLM_DEEP_THINK_MODEL=claude-opus
CRYPTOAGENTS_LLM_QUICK_THINK_MODEL=gpt-4o
CRYPTOAGENTS_TEMPERATURE=0.7

# Trading Parameters
CRYPTOAGENTS_TRADEABLE_CRYPTOS=BTC,ETH,SOL,ARB,OP
CRYPTOAGENTS_MAX_POSITION_SIZE=0.1  # 10% per position
CRYPTOAGENTS_RISK_PER_TRADE=0.02    # 2% portfolio risk

# Framework Tuning
CRYPTOAGENTS_MAX_DEBATE_ROUNDS=3
CRYPTOAGENTS_MAX_RISK_ROUNDS=2
CRYPTOAGENTS_LLM_MAX_RETRIES=3
```

## Development

### Running Tests
```bash
pytest tests/ -v
pytest -m unit         # Unit tests only
pytest -m integration  # Integration tests (requires APIs)
```

### Code Style
```bash
ruff check cryptoagents/
ruff format cryptoagents/
```

## Trading Disclaimer

⚠️ **This framework is for research purposes only.** Trading performance depends on:
- Choice of LLM models
- Market conditions and volatility
- Quality of data from APIs
- Backtesting period and parameters
- Non-deterministic LLM outputs

**This is NOT financial or investment advice.** Use at your own risk with appropriate risk management.

## Roadmap

- [ ] v0.1.0 - Core agent framework & Nansen integration
- [ ] v0.2.0 - Sentiment analysis & social feeds
- [ ] v0.3.0 - Technical analysis & indicators
- [ ] v0.4.0 - Simulated exchange & backtesting
- [ ] v0.5.0 - Live trading (paper trading first)
- [ ] v0.6.0 - Multi-timeframe analysis
- [ ] v0.7.0 - Advanced risk management
- [ ] v1.0.0 - Production release

## Contributing

Contributions welcome! Please:
1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add amazing feature'`)
4. Push to branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

MIT License - see LICENSE file for details

## Citation

If you use CryptoTradingAgents in research, please cite:

```bibtex
@software{cryptotradingagents2026,
  title={CryptoTradingAgents: Multi-Agents LLM Crypto Trading Framework},
  author={Your Name},
  year={2026},
  url={https://github.com/YourUsername/CryptoTradingAgents}
}
```

## Support

- 📖 [Documentation](./docs)
- 🐛 [Issues](https://github.com/YourUsername/CryptoTradingAgents/issues)
- 💬 [Discussions](https://github.com/YourUsername/CryptoTradingAgents/discussions)

---

**Built with ❤️ for the crypto community**
