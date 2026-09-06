"""
Coin Selection Module
Selects random altcoins for autonomous trading based on market criteria
"""

import logging
import os
import random
from typing import Optional, List, Dict
from dataclasses import dataclass

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class CoinCandidate:
    """Candidate coin for trading"""
    symbol: str
    name: str
    market_cap_usd: float
    volume_24h_usd: float
    current_price: float
    market_cap_rank: int
    
    @property
    def liquidity_score(self) -> float:
        """Calculate liquidity score (0-100)"""
        # Normalized volume as percentage of market cap
        if self.market_cap_usd > 0:
            vol_ratio = self.volume_24h_usd / self.market_cap_usd
            return min(100, vol_ratio * 100)
        return 0


class CoinSelector:
    """
    Selects random altcoins for autonomous trading
    Filters by market criteria to ensure sufficient liquidity
    """
    
    def __init__(self, coingecko_api, exclude_symbols: Optional[List[str]] = None):
        """
        Initialize coin selector
        
        Args:
            coingecko_api: CoinGecko API instance
            exclude_symbols: Symbols to exclude (e.g., ['BTC', 'ETH', 'USDT', 'USDC'])
        """
        self.coingecko_api = coingecko_api
        self.exclude_symbols = set(exclude_symbols or ['BTC', 'ETH', 'USDT', 'USDC', 'BUSD', 'DAI'])

        # Tradeability filters (configurable via .env, previously hardcoded)
        self.min_volume_usd = float(os.getenv("HYPERLIQUID_MIN_VOLUME_USD", "10000000"))
        self.min_market_cap_rank = int(os.getenv("HYPERLIQUID_MIN_MARKET_CAP_RANK", "1"))
        self.max_market_cap_rank = int(os.getenv("HYPERLIQUID_MAX_MARKET_CAP_RANK", "500"))
        self.min_liquidity_score = 5
        
        # Cache of candidates
        self.candidates_cache: List[CoinCandidate] = []
        self.last_update = None
        
        logger.info(f"CoinSelector initialized")
        logger.info(f"  Excluded symbols: {', '.join(self.exclude_symbols)}")
        logger.info(f"  Market cap rank range: #{self.min_market_cap_rank}-#{self.max_market_cap_rank}")
        logger.info(f"  Min 24h volume: ${self.min_volume_usd:,.0f}")

    def _is_tradeable(self, candidate: CoinCandidate) -> bool:
        """Check if a candidate meets the configured tradeability filters"""
        return (
            candidate.volume_24h_usd >= self.min_volume_usd and
            self.min_market_cap_rank <= candidate.market_cap_rank <= self.max_market_cap_rank and
            candidate.liquidity_score >= self.min_liquidity_score
        )

    async def fetch_candidates(self, market_data: Optional[Dict] = None) -> List[CoinCandidate]:
        """
        Fetch and filter candidate coins from market data
        
        Args:
            market_data: Optional pre-fetched market data dict
            
        Returns:
            List of tradeable CoinCandidate objects
        """
        try:
            if market_data is None:
                # Fetch from CoinGecko
                market_data = self.coingecko_api.get_market_data(per_page=250, page=1)
            
            candidates = []
            
            for coin in market_data:
                symbol = coin.get('symbol', '').upper()
                
                # Skip excluded symbols
                if symbol in self.exclude_symbols:
                    continue
                
                # Skip if missing data
                if not all([
                    coin.get('current_price'),
                    coin.get('market_cap'),
                    coin.get('total_volume'),
                    coin.get('market_cap_rank')
                ]):
                    continue
                
                candidate = CoinCandidate(
                    symbol=symbol,
                    name=coin.get('name', 'Unknown'),
                    market_cap_usd=coin.get('market_cap', 0),
                    volume_24h_usd=coin.get('total_volume', 0),
                    current_price=coin.get('current_price', 0),
                    market_cap_rank=coin.get('market_cap_rank', 999)
                )
                
                if self._is_tradeable(candidate):
                    candidates.append(candidate)
            
            # Sort by liquidity score (descending)
            candidates.sort(key=lambda x: x.liquidity_score, reverse=True)
            
            self.candidates_cache = candidates
            logger.info(f"[OK] Fetched {len(candidates)} tradeable coin candidates")
            
            return candidates
            
        except Exception as e:
            logger.error(f"Error fetching candidates: {e}")
            return []

    async def select_random_coin(
        self,
        market_data: Optional[Dict] = None,
        weights: str = "liquidity"
    ) -> Optional[CoinCandidate]:
        """
        Select a random coin from candidates
        
        Args:
            market_data: Optional pre-fetched market data
            weights: Weighting scheme - "uniform", "liquidity", or "volume"
            
        Returns:
            Selected CoinCandidate or None if no candidates available
        """
        # Rebuild candidates whenever the caller hands us fresh market data (each trading
        # cycle re-fetches from CoinGecko); only reuse the cache when none was supplied,
        # so prices/volumes/ranks don't stay frozen at whatever they were on the first call
        if market_data is not None or not self.candidates_cache:
            await self.fetch_candidates(market_data)
        
        if not self.candidates_cache:
            logger.warning("No tradeable coins available")
            return None
        
        # Apply weighting scheme
        if weights == "uniform":
            # Equal probability
            return random.choice(self.candidates_cache)
        
        elif weights == "liquidity":
            # Weight by liquidity score
            scores = [c.liquidity_score for c in self.candidates_cache]
            total_score = sum(scores)
            if total_score > 0:
                selected = random.choices(
                    self.candidates_cache,
                    weights=scores,
                    k=1
                )[0]
            else:
                selected = random.choice(self.candidates_cache)
        
        elif weights == "volume":
            # Weight by 24h volume
            volumes = [c.volume_24h_usd for c in self.candidates_cache]
            total_volume = sum(volumes)
            if total_volume > 0:
                selected = random.choices(
                    self.candidates_cache,
                    weights=volumes,
                    k=1
                )[0]
            else:
                selected = random.choice(self.candidates_cache)
        
        else:
            selected = random.choice(self.candidates_cache)
        
        logger.info(f"[OK] Selected coin: {selected.symbol}")
        logger.info(f"  Price: ${selected.current_price:.2f}")
        logger.info(f"  Volume (24h): ${selected.volume_24h_usd:,.0f}")
        logger.info(f"  Market Cap Rank: #{selected.market_cap_rank}")
        logger.info(f"  Liquidity Score: {selected.liquidity_score:.1f}/100")
        
        return selected

    async def select_n_random_coins(
        self,
        n: int = 5,
        market_data: Optional[Dict] = None,
        weights: str = "liquidity"
    ) -> List[CoinCandidate]:
        """
        Select N random coins
        
        Args:
            n: Number of coins to select
            market_data: Optional pre-fetched market data
            weights: Weighting scheme - "uniform", "liquidity", or "volume"
            
        Returns:
            List of selected CoinCandidate objects
        """
        # Rebuild candidates whenever the caller hands us fresh market data (each trading
        # cycle re-fetches from CoinGecko); only reuse the cache when none was supplied,
        # so prices/volumes/ranks don't stay frozen at whatever they were on the first call
        if market_data is not None or not self.candidates_cache:
            await self.fetch_candidates(market_data)
        
        if not self.candidates_cache:
            return []
        
        n = min(n, len(self.candidates_cache))

        raw_weights = None
        if weights == "liquidity":
            raw_weights = [c.liquidity_score for c in self.candidates_cache]
        elif weights == "volume":
            raw_weights = [c.volume_24h_usd for c in self.candidates_cache]

        if raw_weights and sum(raw_weights) > 0 and n < len(self.candidates_cache):
            probabilities = np.array(raw_weights, dtype=float)
            probabilities = probabilities / probabilities.sum()
            indices = np.random.choice(len(self.candidates_cache), size=n, replace=False, p=probabilities)
            selected = [self.candidates_cache[i] for i in indices]
        else:
            selected = random.sample(self.candidates_cache, n)
        
        logger.info(f"[OK] Selected {len(selected)} random coins (weighting: {weights}):")
        for coin in selected:
            logger.info(f"  - {coin.symbol}: ${coin.current_price:.2f} (Volume: ${coin.volume_24h_usd:,.0f})")
        
        return selected

    def get_top_candidates(self, n: int = 10) -> List[CoinCandidate]:
        """Get top N candidates by liquidity score"""
        return self.candidates_cache[:n]

    def get_statistics(self) -> dict:
        """Get statistics on candidate pool"""
        if not self.candidates_cache:
            return {
                "total_candidates": 0,
                "avg_liquidity": 0,
                "avg_volume": 0,
                "avg_price": 0
            }
        
        return {
            "total_candidates": len(self.candidates_cache),
            "avg_liquidity": sum(c.liquidity_score for c in self.candidates_cache) / len(self.candidates_cache),
            "avg_volume": sum(c.volume_24h_usd for c in self.candidates_cache) / len(self.candidates_cache),
            "avg_price": sum(c.current_price for c in self.candidates_cache) / len(self.candidates_cache),
            "total_24h_volume": sum(c.volume_24h_usd for c in self.candidates_cache),
            "total_market_cap": sum(c.market_cap_usd for c in self.candidates_cache)
        }
