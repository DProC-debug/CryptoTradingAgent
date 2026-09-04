"""
Debug the /perp/account endpoint call
"""
import asyncio
import os
from dotenv import dotenv_values
import aiohttp

env = dotenv_values('.env')

NANSEN_API_KEY = env['NANSEN_API_KEY']
PORTFOLIO_WALLET = env['PORTFOLIO_WALLET_HYPERLIQUID']
NANSEN_BASE_URL = "https://api.nansen.ai/api/v1"

async def main():
    async with aiohttp.ClientSession() as session:
        print(f"Wallet: {PORTFOLIO_WALLET}")
        print(f"API Key: {NANSEN_API_KEY[:10]}...")
        print()
        
        print(f"Calling: GET {NANSEN_BASE_URL}/perp/account")
        async with session.get(
            f"{NANSEN_BASE_URL}/perp/account",
            params={"wallet_address": PORTFOLIO_WALLET},
            headers={"apikey": NANSEN_API_KEY}
        ) as response:
            print(f"Status: {response.status}")
            print(f"Content-Type: {response.headers.get('content-type')}")
            
            if response.status == 200:
                result = await response.json()
                print(f"Response body:")
                import json
                print(json.dumps(result, indent=2))
            else:
                text = await response.text()
                print(f"Error response:")
                print(text)

asyncio.run(main())
