import os, asyncio, json
import aiohttp
from dotenv import dotenv_values


env = dotenv_values('.env')
os.environ.update({k: v for k, v in env.items() if v is not None})

async def main():
    api_key = os.getenv('NANSEN_API_KEY')
    wallet = os.getenv('PORTFOLIO_WALLET_HYPERLIQUID')
    payload = {
        'wallet_address': wallet,
        'coin': 'BTC',
        'is_buy': True,
        'size': 0.000642,
        'price': 77862.0,
        'order_type': 'market',
        'slippage': 0.03,
        'leverage': 1,
    }
    print('payload', payload)
    async with aiohttp.ClientSession() as session:
        async with session.post('https://api.nansen.ai/api/v1/perp/order', json=payload, headers={'apikey': api_key, 'Content-Type': 'application/json'}) as resp:
            body = await resp.text()
            print('STATUS', resp.status)
            print(body[:4000])

asyncio.run(main())
