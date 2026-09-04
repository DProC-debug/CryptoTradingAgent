import asyncio
import os
from dotenv import dotenv_values
from cryptoagents.exchanges.hyperliquid_trader import HyperliquidTrader
from cryptoagents.dataflows.coingecko_api import CoinGeckoAPI


env = dotenv_values('.env')
os.environ.update({k: v for k, v in env.items() if v is not None})


async def main():
    api_key = os.getenv('NANSEN_API_KEY')
    wallet = os.getenv('PORTFOLIO_WALLET_HYPERLIQUID')
    pk = os.getenv('PORTFOLLET_WALLET_PRIVATE_KEY') or os.getenv('PORTFOLIO_WALLET_PRIVATE_KEY')

    print('API_KEY_SET:', bool(api_key))
    print('WALLET_SET:', bool(wallet))
    print('PK_SET:', bool(pk))

    rows = CoinGeckoAPI().get_market_data(per_page=250, page=1)
    btc_price = next(
        (float(coin.get('current_price') or 0) for coin in rows if str(coin.get('symbol', '')).upper() == 'BTC'),
        60000.0,
    )
    print('BTC_PRICE_FOR_TEST:', btc_price)

    trader = HyperliquidTrader(api_key, wallet, pk, max_leverage=20)
    async with trader as t:
        balance_before = await t.get_account_balance()
        print('BALANCE_BEFORE:', balance_before)

        result = await t.open_position(
            symbol='BTC',
            is_buy=True,
            size_usd=50,
            leverage=1,
            slippage=0.03,
            price=btc_price,
            order_type='market',
        )
        print('ORDER_SUCCESS:', result.success)
        print('ORDER_SYMBOL:', result.symbol)
        print('ORDER_SIDE:', result.side)
        print('ORDER_ENTRY_PRICE:', result.entry_price)
        print('ORDER_SIZE:', result.size)
        print('ORDER_LEVERAGE:', result.leverage)
        print('ORDER_ERROR:', result.error)


asyncio.run(main())
