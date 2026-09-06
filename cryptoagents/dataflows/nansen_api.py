"""Nansen API wrapper for blockchain on-chain analytics"""

import logging

import requests

logger = logging.getLogger(__name__)


class NansenAPI:
    """Client for Nansen on-chain analytics API
    
    API Documentation: https://docs.nansen.ai/
    Uses POST requests with apikey header authentication
    """

    BASE_URL = "https://api.nansen.ai/api/v1"

    def __init__(self, api_key: str):
        """Initialize Nansen API client

        Args:
            api_key: Nansen API key
        """
        if not api_key:
            raise ValueError("NANSEN_API_KEY not set in environment")

        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "apikey": api_key,
            "Content-Type": "application/json",
            "Accept": "*/*"
        })

    def _post(self, endpoint: str, data: dict) -> dict:
        """Make POST request to Nansen API

        Args:
            endpoint: API endpoint path (without /api/v1 prefix)
            data: Request body data

        Returns:
            Response JSON
        """
        url = f"{self.BASE_URL}/{endpoint}"
        try:
            response = self.session.post(url, json=data, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            logger.error(f"Nansen API request failed: {e}")
            raise

    def get_address_balance(
        self,
        address: str,
        chain: str = "ethereum",
        hide_spam: bool = True,
        page: int = 1,
        per_page: int = 10,
    ) -> dict:
        """Get current token balance for an address

        Args:
            address: Wallet address (0x...)
            chain: Blockchain name ('ethereum', 'polygon', 'arbitrum', etc)
            hide_spam: Hide spam/scam tokens
            page: Pagination page
            per_page: Results per page

        Returns:
            Address balance data with token holdings
        """
        data = {
            "address": address,
            "chain": chain,
            "hide_spam_token": hide_spam,
            "pagination": {
                "page": page,
                "per_page": per_page
            }
        }

        try:
            result = self._post("profiler/address/current-balance", data)
            return result
        except Exception as e:
            logger.error(f"Error fetching address balance: {e}")
            return {}

    def get_token_position_intelligence(self, token_symbol: str) -> dict:
        """Get aggregated Hyperliquid perp positioning by trader cohort for a token

        Works for any Hyperliquid-tradeable symbol (not just EVM wallet addresses) -
        returns net long/short USD exposure broken down by Smart Money, Whales, and
        Public Figures. Unknown/untraded symbols return all-zero values, not an error.

        Args:
            token_symbol: Token symbol as traded on Hyperliquid (e.g. 'BTC', 'WLD')

        Returns:
            Dict with smart_trader/whale/public_figure longs/shorts/total in USD
        """
        try:
            result = self._post("tgm/position-intelligence", {"token_address": token_symbol})
            data = result.get("data", [])
            return data[0] if data else {}
        except Exception as e:
            logger.error(f"Error fetching position intelligence for {token_symbol}: {e}")
            return {}

    def get_address_portfolio(
        self,
        address: str,
        chain: str = "ethereum",
    ) -> dict:
        """Get portfolio summary for an address

        Args:
            address: Wallet address (0x...)
            chain: Blockchain name

        Returns:
            Portfolio summary data (use get_address_balance instead)
        """
        # Note: This endpoint may not be available in all API tiers
        # Use get_address_balance as alternative
        logger.warning("get_address_portfolio may not be available, using get_address_balance")
        return self.get_address_balance(address, chain)

    def health_check(self) -> bool:
        """Check if API is accessible and authenticated

        Returns:
            True if API key is valid, False otherwise
        """
        try:
            # Try a simple request with a dummy address to verify auth
            data = {
                "address": "0x0000000000000000000000000000000000000000",
                "chain": "ethereum"
            }
            response = self.session.post(
                f"{self.BASE_URL}/profiler/address/current-balance",
                json=data,
                timeout=10
            )
            # Check authentication errors
            if response.status_code == 401:
                logger.error("Nansen API authentication failed: Invalid API key")
                return False
            elif response.status_code == 403:
                logger.error("Nansen API authentication failed: Forbidden/No permission")
                return False
            # Any other response means we reached the API
            logger.debug(f"Nansen health check: Status {response.status_code}")
            return True
        except Exception as e:
            logger.debug(f"Nansen health check failed: {e}")
            return False
