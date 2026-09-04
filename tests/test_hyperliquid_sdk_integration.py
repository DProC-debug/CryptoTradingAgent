import pytest

from cryptoagents.exchanges import hyperliquid_trader as module


class DummyExchange:
    def __init__(self, config=None):
        self.config = config or {}
        self.calls = []

    def fetch_balance(self, params=None):
        self.calls.append(("fetch_balance", params))
        return {"USDC": {"total": 250.0, "free": 250.0}}

    def create_order(self, *args, **kwargs):
        self.calls.append(("create_order", args, kwargs))
        return {"status": "ok", "response": {"type": "order", "data": {"statuses": [{"resting": {"oid": 123}}]}}}


def test_hyperliquid_trader_uses_official_sdk(monkeypatch):
    captured = {}

    def fake_sdk(config=None):
        captured["config"] = config
        return DummyExchange(config)

    monkeypatch.setattr(module, "HyperliquidSync", fake_sdk)

    trader = module.HyperliquidTrader(
        nansen_api_key="demo-key",
        wallet_address="0x1111111111111111111111111111111111111111",
        wallet_private_key="1111111111111111111111111111111111111111111111111111111111111111",
        max_leverage=20,
    )

    assert trader.exchange is not None
    assert trader.exchange.config["walletAddress"] == "0x053a426493373738379739393393938983"
    assert trader.exchange.config["privateKey"].startswith("0x")
    assert trader.exchange.config["options"]["defaultSlippage"] == 0.05
