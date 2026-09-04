"""CoinGecko API wrapper for cryptocurrency market data"""

import logging
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class CoinGeckoAPI:
    """Client for CoinGecko cryptocurrency market data API"""

    BASE_URL = "https://api.coingecko.com/api/v3"
    FREE_TIER_DELAY = 2.0  # seconds between requests for free tier (conservative)

    def __init__(self, api_key: Optional[str] = None):
        """Initialize CoinGecko API client

        Args:
            api_key: Optional CoinGecko API key for higher rate limits
        """
        self.api_key = api_key
        self.last_request_time = 0
        self.retry_count = 5  # Increased retry attempts
        self.retry_delay = 3  # Increased base delay
        self.cache = {}  # Simple in-memory cache
        self.cache_ttl = 60  # Cache for 60 seconds

    def _wait_for_rate_limit(self) -> None:
        """Wait to respect rate limiting"""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.FREE_TIER_DELAY:
            wait_time = self.FREE_TIER_DELAY - elapsed
            logger.debug(f"Rate limiting: waiting {wait_time:.1f}s")
            time.sleep(wait_time)

    def _get(self, endpoint: str, params: Optional[dict] = None) -> dict:
        """Make GET request to CoinGecko API with retry logic

        Args:
            endpoint: API endpoint path
            params: Query parameters

        Returns:
            Response JSON
        """
        url = f"{self.BASE_URL}/{endpoint}"
        if params is None:
            params = {}


        headers = {"User-Agent": "CryptoTradingAgents/0.1.0"}
        
        # Check cache first
        cache_key = f"{endpoint}:{sorted(params.items())}"
        if cache_key in self.cache:
            cached_data, cached_time = self.cache[cache_key]
            if time.time() - cached_time < self.cache_ttl:
                logger.debug(f"Cache hit for {endpoint}")
                return cached_data
        
        for attempt in range(self.retry_count):
            try:
                self._wait_for_rate_limit()
                self.last_request_time = time.time()
                
                response = requests.get(url, params=params, headers=headers, timeout=30)
                response.raise_for_status()
                result = response.json()
                # Cache successful response
                self.cache[cache_key] = (result, time.time())
                return result
                
            except requests.exceptions.HTTPError as e:
                # Rate limiting - retry with backoff
                if response.status_code == 429:
                    if attempt < self.retry_count - 1:
                        wait_time = self.retry_delay * (2 ** attempt)
                        logger.warning(
                            f"Rate limited (429). Retrying in {wait_time}s "
                            f"(attempt {attempt + 1}/{self.retry_count})"
                        )
                        time.sleep(wait_time)
                        continue
                    else:
                        logger.error(f"Rate limited after {self.retry_count} attempts")
                        raise
                else:
                    logger.error(f"CoinGecko API error: {e}")
                    raise
                    
            except requests.RequestException as e:
                logger.error(f"CoinGecko API request failed: {e}")
                raise

        return {}

    def get_crypto_data(
        self,
        crypto_ids: list[str],
        vs_currency: str = "usd",
        include_market_cap: bool = True,
        include_24h_vol: bool = True,
        include_24h_change: bool = True,
    ) -> dict:
        """Get current market data for cryptocurrencies

        Args:
            crypto_ids: List of crypto IDs (e.g., ['bitcoin', 'ethereum'])
            vs_currency: Target currency ('usd', 'eur', etc)
            include_market_cap: Include market cap data
            include_24h_vol: Include 24h volume
            include_24h_change: Include 24h price change

        Returns:
            Dictionary with crypto market data
        """
        params = {
            "ids": ",".join(crypto_ids),
            "vs_currencies": vs_currency,
        }
        
        if include_market_cap:
            params["include_market_cap"] = "true"
        if include_24h_vol:
            params["include_24h_vol"] = "true"
        if include_24h_change:
            params["include_24h_change"] = "true"

        try:
            data = self._get("simple/price", params)
            return data
        except Exception as e:
            logger.error(f"Error fetching crypto data: {e}")
            return {}

    def get_market_data(
        self,
        vs_currency: str = "usd",
        order: str = "market_cap_desc",
        per_page: int = 100,
        page: int = 1,
        include_24h_change: bool = True,
    ) -> list[dict]:
        """Get market data for top cryptocurrencies

        Args:
            vs_currency: Target currency
            order: Sort order ('market_cap_desc', 'gecko_desc', etc)
            per_page: Results per page
            page: Page number
            include_24h_change: Include 24h change percentage

        Returns:
            List of cryptocurrency market data
        """
        params = {
            "vs_currency": vs_currency,
            "order": order,
            "per_page": per_page,
            "page": page,
        }

        try:
            data = self._get("coins/markets", params)
            return data
        except Exception as e:
            logger.error(f"Error fetching market data: {e}")
            return []

    def get_historical_data(
        self, crypto_id: str, vs_currency: str = "usd", days: int = 7
    ) -> dict:
        """Get historical price data

        Args:
            crypto_id: Cryptocurrency ID
            vs_currency: Target currency
            days: Number of days (1, 7, 30, 90, 365, etc)

        Returns:
            Historical data dictionary
        """
        params = {
            "vs_currency": vs_currency,
            "days": days,
        }

        try:
            data = self._get(f"coins/{crypto_id}/market_chart", params)
            return data
        except Exception as e:
            logger.error(f"Error fetching historical data: {e}")
            return {}

    def get_global_data(self, vs_currency: str = "usd") -> dict:
        """Get global cryptocurrency market data

        Args:
            vs_currency: Target currency

        Returns:
            Global market data (BTC dominance, market cap, volume, etc)
        """
        try:
            data = self._get("global")
            return data.get("data", {})
        except Exception as e:
            logger.error(f"Error fetching global data: {e}")
            return {}

    def get_coin_details(self, coin_id: str) -> dict:
        """Get full coin detail record (supply, sentiment votes, watchlist, categories)

        Note: developer_data/community_data return empty on the free tier - only
        market_data, sentiment votes, watchlist counts, and categories are populated.

        Args:
            coin_id: CoinGecko coin id (e.g. 'bitcoin')

        Returns:
            Full coin detail dict, or {} on failure
        """
        try:
            return self._get(
                f"coins/{coin_id}",
                {
                    "localization": "false",
                    "tickers": "false",
                    "market_data": "true",
                    "community_data": "true",
                    "developer_data": "true",
                    "sparkline": "false",
                },
            )
        except Exception as e:
            logger.error(f"Error fetching coin details for {coin_id}: {e}")
            return {}

    def get_trending(self, order: str = "gecko_desc") -> list[dict]:
        """Get trending cryptocurrencies

        Args:
            order: Sort order

        Returns:
            List of trending coins
        """
        try:
            data = self._get("search/trending")
            return data.get("coins", [])
        except Exception as e:
            logger.error(f"Error fetching trending data: {e}")
            return []

    def search_crypto(self, query: str) -> list[dict]:
        """Search for cryptocurrency by name or symbol

        Args:
            query: Search query

        Returns:
            List of matching cryptocurrencies
        """
        try:
            data = self._get("search", {"query": query})
            return data.get("coins", [])
        except Exception as e:
            logger.error(f"Error searching cryptos: {e}")
            return []

    def get_crypto_by_symbol(self, symbol: str, vs_currency: str = "usd") -> dict:
        """Get crypto data by symbol

        Args:
            symbol: Crypto symbol (BTC, ETH, SOL, etc)
            vs_currency: Target currency

        Returns:
            Crypto data
        """
        # Map common symbols to CoinGecko IDs
        symbol_map = {
            "BTC": "bitcoin",
            "ETH": "ethereum",
            "SOL": "solana",
            "ARB": "arbitrum",
            "OP": "optimism",
            "ADA": "cardano",
            "XRP": "ripple",
            "DOGE": "dogecoin",
            "LTC": "litecoin",
            "BCH": "bitcoin-cash",
        }

        crypto_id = symbol_map.get(symbol.upper())
        if not crypto_id:
            logger.warning(f"Symbol {symbol} not found in symbol map, searching...")
            results = self.search_crypto(symbol)
            if results:
                crypto_id = results[0]["id"]
            else:
                return {}

        try:
            data = self._get(
                f"simple/price",
                {
                    "ids": crypto_id,
                    "vs_currencies": vs_currency,
                    "include_market_cap": "true",
                    "include_24h_vol": "true",
                    "include_24h_change": "true",
                },
            )
            result = data.get(crypto_id, {})
            if result:
                result["id"] = crypto_id  # Needed by callers fetching historical data
            return result
        except Exception as e:
            logger.error(f"Error fetching {symbol} data: {e}")
            return {}

    def health_check(self) -> bool:
        """Check if API is accessible

        Returns:
            True if API is accessible, False otherwise
        """
        try:
            self._get("ping")
            return True
        except Exception:
            return False
