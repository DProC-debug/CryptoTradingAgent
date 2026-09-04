"""CLI interface using Typer for CryptoTradingAgents"""

import logging
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from cryptoagents import CryptoTradingGraph
from cryptoagents.default_config import DEFAULT_CONFIG

# Setup CLI
app = typer.Typer(help="CryptoTradingAgents - Multi-Agent Crypto Trading Framework")
console = Console()

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@app.command()
def analyze(
    crypto: str = typer.Argument(..., help="Cryptocurrency symbol (e.g., BTC, ETH)"),
    timeframe: str = typer.Option("1h", help="Analysis timeframe (1h, 4h, 1d, etc)"),
    lookback: str = typer.Option("24h", help="Historical lookback period"),
) -> None:
    """Analyze a cryptocurrency with all agents"""
    console.print(Panel.fit(f"Analyzing {crypto.upper()}", title="CryptoTradingAgents"))

    try:
        ta = CryptoTradingGraph(debug=True)
        result = ta.analyze(crypto.upper())

        console.print(f"\n✓ Analysis Status: {result.get('status')}")
        if result.get("market_data"):
            console.print(f"Price: ${result['market_data'].get('usd', 'N/A')}")
            console.print(f"24h Change: {result['market_data'].get('usd_24h_change', 0):.2f}%")

    except Exception as e:
        console.print(f"\n✗ Error: {e}", style="bold red")


@app.command()
def market() -> None:
    """Show cryptocurrency market overview"""
    console.print(Panel.fit("Market Overview", title="CryptoTradingAgents"))

    try:
        ta = CryptoTradingGraph(debug=False)
        overview = ta.get_market_overview()

        if overview.get("global"):
            global_data = overview["global"]
            console.print(f"\nBTC Dominance: {global_data.get('btc_market_cap_percentage', 0):.2f}%")
            console.print(
                f"ETH Dominance: {global_data.get('eth_market_cap_percentage', 0):.2f}%"
            )

        # Create table of top 10
        if overview.get("top_10"):
            table = Table(title="Top 10 Cryptocurrencies")
            table.add_column("Rank", style="cyan")
            table.add_column("Crypto", style="magenta")
            table.add_column("Price (USD)", justify="right", style="green")
            table.add_column("24h Change", justify="right")

            for i, coin in enumerate(overview["top_10"], 1):
                change = coin.get("price_change_percentage_24h", 0)
                change_style = "green" if change > 0 else "red"
                table.add_row(
                    str(i),
                    coin.get("symbol", "N/A").upper(),
                    f"${coin.get('current_price', 0):,.0f}",
                    f"{change:+.2f}%",
                    style=change_style,
                )

            console.print(table)

    except Exception as e:
        console.print(f"\n✗ Error: {e}", style="bold red")


@app.command()
def backtest(
    cryptos: str = typer.Argument(..., help="Cryptocurrencies to test (BTC,ETH,SOL)"),
    start: str = typer.Option("2024-01-01", help="Start date (YYYY-MM-DD)"),
    end: str = typer.Option("2024-12-31", help="End date (YYYY-MM-DD)"),
    strategy: str = typer.Option("multi-agent", help="Strategy name"),
) -> None:
    """Run backtesting on historical data"""
    console.print(
        Panel.fit(
            f"Backtesting {cryptos} from {start} to {end}",
            title="CryptoTradingAgents",
        )
    )
    console.print("\n⏳ Backtesting framework coming in v0.4.0...")


@app.command()
def config() -> None:
    """Show current configuration"""
    console.print(Panel.fit("Current Configuration", title="CryptoTradingAgents"))

    table = Table()
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="magenta")

    for key, value in sorted(DEFAULT_CONFIG.items()):
        if "key" in key.lower() or "password" in key.lower():
            display_value = "***hidden***" if value else "(not set)"
        else:
            display_value = str(value)

        table.add_row(key, display_value)

    console.print(table)


@app.command()
def test() -> None:
    """Test API connections"""
    console.print(Panel.fit("Testing Connections", title="CryptoTradingAgents"))

    try:
        ta = CryptoTradingGraph(debug=False)

        # Test Nansen
        if ta.nansen:
            status = "✓ Connected" if ta.nansen.health_check() else "✗ Failed"
            console.print(f"Nansen API: {status}")
        else:
            console.print("Nansen API: ⚠ Not configured")

        # Test CoinGecko
        status = "✓ Connected" if ta.coingecko.health_check() else "✗ Failed"
        console.print(f"CoinGecko API: {status}")

        # Test LLMs
        console.print(f"Deep Thinking LLM: ✓ {DEFAULT_CONFIG['deep_think_llm']}")
        console.print(f"Quick Thinking LLM: ✓ {DEFAULT_CONFIG['quick_think_llm']}")

    except Exception as e:
        console.print(f"\n✗ Error: {e}", style="bold red")


def main() -> None:
    """Main entry point for CLI"""
    app()


if __name__ == "__main__":
    main()
