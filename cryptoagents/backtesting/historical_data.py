"""Historical data utilities for backtesting"""

import logging
from datetime import datetime, timedelta
from typing import List, Tuple, Optional

logger = logging.getLogger(__name__)


class HistoricalDataFetcher:
    """Fetches historical price data for backtesting"""
    
    def __init__(self, coingecko_api):
        """
        Initialize Historical Data Fetcher
        
        Args:
            coingecko_api: CoinGeckoAPI instance
        """
        self.coingecko = coingecko_api
    
    def fetch_daily_prices(
        self,
        symbol: str,
        days: int = 90,
        end_date: Optional[datetime] = None
    ) -> List[Tuple[datetime, float]]:
        """
        Fetch real daily historical prices for a symbol from CoinGecko

        Args:
            symbol: Cryptocurrency symbol (e.g., 'BTC', 'ETH')
            days: Number of days of history to fetch
            end_date: Unused - CoinGecko's market_chart endpoint only returns
                "N days up to now", not an arbitrary past range. Kept for
                backward compatibility with callers.

        Returns:
            List of (datetime, price) tuples, one per day, sorted ascending
        """
        logger.info(f"Fetching {days} days of historical data for {symbol}")

        coin_id = self.coingecko.resolve_coin_id(symbol)
        if not coin_id:
            logger.warning(f"Could not resolve {symbol} to a CoinGecko coin id - using simulated data")
            return self._generate_simulated_prices(symbol, days, end_date or datetime.now())

        try:
            data = self.coingecko.get_historical_data(coin_id, days=days)
            raw_prices = data.get("prices", [])
        except Exception as e:
            logger.warning(f"Error fetching historical data for {symbol}: {e}")
            raw_prices = []

        if not raw_prices:
            logger.warning(f"No historical data returned for {symbol} - using simulated data")
            return self._generate_simulated_prices(symbol, days, end_date or datetime.now())

        # CoinGecko returns hourly (or finer) granularity depending on range - keep
        # one sample (the last seen that day) per calendar date to get daily prices
        by_date = {}
        for timestamp_ms, price in raw_prices:
            dt = datetime.fromtimestamp(timestamp_ms / 1000)
            by_date[dt.date()] = (dt, price)

        prices = sorted(by_date.values(), key=lambda x: x[0])
        logger.info(
            f"Fetched {len(prices)} real daily price points for {symbol} "
            f"({prices[0][0].date()} to {prices[-1][0].date()})"
        )
        return prices
    
    def _generate_simulated_prices(
        self,
        symbol: str,
        days: int,
        end_date: datetime
    ) -> List[Tuple[datetime, float]]:
        """
        Generate simulated historical prices for demonstration
        
        Args:
            symbol: Cryptocurrency symbol
            days: Number of days to simulate
            end_date: End date for simulation
        
        Returns:
            List of (datetime, price) tuples with realistic price movements
        """
        logger.info(f"Generating simulated historical data for {symbol}")
        
        # Base prices for common symbols
        base_prices = {
            "BTC": 78489,
            "ETH": 2456,
            "SOL": 142,
            "USDC": 1.00,
        }
        
        start_price = base_prices.get(symbol.upper(), 100)
        
        prices = []
        current_date = end_date - timedelta(days=days)
        current_price = start_price * 0.85  # Start 15% below current
        
        # Generate price movements
        import random
        random.seed(42)  # Reproducible
        
        for i in range(days):
            # Random walk with slight uptrend
            daily_return = random.gauss(0.001, 0.03)  # Mean 0.1%, std 3%
            current_price = current_price * (1 + daily_return)
            
            prices.append((current_date, current_price))
            current_date += timedelta(days=1)
        
        logger.info(f"Generated {len(prices)} simulated price points for {symbol}")
        logger.info(f"Price range: ${min(p[1] for p in prices):,.2f} - ${max(p[1] for p in prices):,.2f}")
        
        return prices
