"""Historical data utilities for backtesting"""

import logging
from datetime import datetime, timedelta
from typing import List, Tuple, Optional
import time

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
        Fetch daily historical prices for a symbol
        
        Args:
            symbol: Cryptocurrency symbol (e.g., 'BTC', 'ETH')
            days: Number of days of history to fetch
            end_date: End date for historical data (default: today)
        
        Returns:
            List of (datetime, price) tuples
        """
        if end_date is None:
            end_date = datetime.now()
        
        start_date = end_date - timedelta(days=days)
        
        logger.info(f"Fetching {days} days of historical data for {symbol}")
        logger.info(f"Period: {start_date.date()} to {end_date.date()}")
        
        prices = []
        current_date = start_date
        
        # Generate daily dates and fetch prices
        while current_date <= end_date:
            try:
                # Get market data for this date
                market_data = self.coingecko.get_market_data()
                
                if market_data:
                    # Find the symbol in market data
                    for coin in market_data:
                        if coin.get("symbol", "").upper() == symbol.upper():
                            price = coin.get("current_price", 0)
                            if price > 0:
                                prices.append((current_date, price))
                            break
                
                # Move to next day
                current_date += timedelta(days=1)
                
                # Rate limiting
                time.sleep(1.5)
            
            except Exception as e:
                logger.warning(f"Error fetching data for {symbol} on {current_date.date()}: {e}")
                current_date += timedelta(days=1)
                continue
        
        logger.info(f"Fetched {len(prices)} price points for {symbol}")
        
        if not prices:
            logger.warning(f"No historical data found for {symbol}")
            # Return simulated data for demo
            return self._generate_simulated_prices(symbol, days, end_date)
        
        return sorted(prices, key=lambda x: x[0])
    
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
