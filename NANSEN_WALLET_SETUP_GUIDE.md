# Nansen API Wallet Setup & Configuration Guide

## Overview

The Nansen API requires **careful wallet initialization** and configuration before you can execute trades on Hyperliquid. This guide covers all wallet setup requirements, environment variables, and prerequisites for live trading.

---

## 1. Environment Variables Required for Nansen Trading

### Essential Variables

```bash
# Required for API authentication
NANSEN_API_KEY=nsn_xxxxxxxxxxxxxxxxxxxxxxxx

# Required for wallet operations
PORTFOLIO_WALLET_HYPERLIQUID=0x1234567890abcdef...    # Your trading wallet address
PORTFOLIO_WALLET_PRIVATE_KEY=0x9876543210fedcba...    # Private key for signing (KEEP SECURE!)
```

### Optional/Derived Variables
```bash
# These may be auto-derived from the main wallet:
PORTFOLIO_WALLET_ADDRESS=0x...                         # Alternative naming
HYPERLIQUID_MAX_LEVERAGE=20                           # Max leverage setting
```

### Storage Locations
- **Primary**: `.env` file in project root
- **Template**: `.env.example` (copy and fill)
- **Never commit**: `.env` should be in `.gitignore`

---

## 2. API Wallet vs User Wallet Configuration

### Key Distinction

| Aspect | API Wallet | User Wallet |
|--------|-----------|-------------|
| **Nansen API Key** | Authenticates your API calls | Not needed for this |
| **User Wallet Address** | `PORTFOLIO_WALLET_HYPERLIQUID` | Your actual trading account |
| **Private Key** | `PORTFOLIO_WALLET_PRIVATE_KEY` | Used to sign EIP-712 transactions |
| **Purpose** | API authentication | Fund operations & trade signing |

### How They Work Together

```
┌─────────────────────────────────────────────────────┐
│              Your Nansen Account                     │
│                                                     │
│  API Key: nsn_xxxxxxx                             │
│  ↓                                                  │
│  [Authenticates all API calls]                     │
│                                                     │
│  Your Connected Wallet: 0x1234...                 │
│  ├─ API key authorizes this wallet on Nansen      │
│  ├─ Private key signs transactions                │
│  └─ All trades execute through THIS wallet       │
└─────────────────────────────────────────────────────┘
```

---

## 3. Wallet Initialization & Registration Steps

### Step 1: Register Wallet with Nansen

**Method**: Through Nansen web interface
1. Visit [https://www.nansen.ai](https://www.nansen.ai)
2. Sign up or log in
3. Connect your wallet (MetaMask, Ledger, etc.)
4. Copy your wallet address exactly (0x...)

**Verification Code**:
```python
from eth_account import Account
from eth_keys import keys

# Verify wallet address matches private key
private_key = "0x..."
account = Account.from_key(private_key)
print(f"Wallet Address: {account.address}")
# Compare with PORTFOLIO_WALLET_HYPERLIQUID
```

### Step 2: Generate API Key

1. In Nansen dashboard → Account Settings → API Keys
2. Create new API key
3. Copy the full key: `nsn_xxxxxxxxxxxxxxxxxxxxxx`
4. Save to `.env` as `NANSEN_API_KEY`

### Step 3: Fund Your Wallet

**Critical**: Your wallet must have:
- ✅ USDC for trading margin
- ✅ Small amount of ETH for gas (if using L2s)

**Funding Sources**:
- Transfer USDC to your Hyperliquid wallet
- Use centralized exchange withdrawal
- Bridge funds from Ethereum/Polygon/Arbitrum

**Check Funding**:
```python
from cryptoagents.exchanges import HyperliquidTrader

trader = HyperliquidTrader(
    nansen_api_key=os.getenv("NANSEN_API_KEY"),
    wallet_address=os.getenv("PORTFOLIO_WALLET_HYPERLIQUID"),
    wallet_private_key=os.getenv("PORTFOLIO_WALLET_PRIVATE_KEY")
)

# Check balance
balance_info = await trader.get_account_balance()
print(f"Total USDC Available: ${balance_info['total_usdc']}")
```

### Step 4: Split USDC Between Spot and Perpetuals

**Important**: Hyperliquid maintains TWO separate USDC balances:

```
Hyperliquid Wallet
├─ Spot USDC (NOT usable for margin/trading)
└─ Perpetuals USDC (CAN be used for trading)

Both count toward available margin, but spot → perps transfer may be needed.
```

**Transfer USDC Script**:
```bash
python cli/transfer_usdc_to_perps.py
```

This 3-step flow:
1. **Prepare**: GET unsigned transfer action from Nansen
2. **Sign**: Sign locally with your private key
3. **Execute**: Submit signed transfer

---

## 4. Configuration Required Before Execute Endpoint

### 4a. Wallet Configuration

Before calling `/perp/execute`, ensure:

✅ **Wallet address is registered with Nansen**
```python
wallet = os.getenv("PORTFOLIO_WALLET_HYPERLIQUID")
assert wallet.startswith("0x"), "Invalid wallet format"
assert len(wallet) == 42, "Invalid wallet length"
```

✅ **Private key matches wallet**
```python
from eth_account import Account

pk = os.getenv("PORTFOLIO_WALLET_PRIVATE_KEY")
account = Account.from_key(pk)
assert account.address.lower() == wallet.lower(), "Private key mismatch!"
```

✅ **Account has sufficient USDC balance**
```python
balance_info = await trader.get_account_balance()
assert balance_info['total_usdc'] >= 1000, "Insufficient USDC for trades"
```

### 4b. Builder Fee Approval (One-Time Requirement)

**What is Builder Fee?**
- Nansen requires a one-time authorization to place orders
- This is an EIP-712 signature, not a fund transfer
- No private key sharing required - you sign locally

**Check Status**:
```python
status = await trader.check_builder_fee_status()
print(f"Approved: {status.get('approved')}")
print(f"Required fee: {status.get('required_fee')}")
```

**Approval Flow if Needed**:
```
1. Agent calls /perp/approve-builder-fee
   ↓
2. Nansen returns EIP-712 payload
   ↓
3. You sign locally with private key
   ↓
4. Agent calls /perp/execute with signature
   ↓
5. Approval complete - ready to trade
```

**Full Approval Example**:
```python
# Step 1: Request approval (returns EIP712 data)
async with session.post(
    "https://api.nansen.ai/api/v1/perp/approve-builder-fee",
    json={"wallet_address": wallet_address},
    headers={"apikey": api_key, "Content-Type": "application/json"}
) as resp:
    approval_data = await resp.json()
    action = approval_data['action']
    nonce = approval_data['nonce']

# Step 2: Sign EIP-712 locally
signature = sign_eip712_message(private_key, eip712_data)

# Step 3: Execute approval
execute_payload = {
    'action': action,
    'nonce': nonce,
    'signature': signature
}

async with session.post(
    "https://api.nansen.ai/api/v1/perp/execute",
    json=execute_payload,
    headers={"apikey": api_key, "Content-Type": "application/json"}
) as resp:
    result = await resp.json()
    print(f"Approval Status: {result.get('status')}")
```

### 4c. Order Configuration Parameters

Before `/perp/execute` can process trades:

```python
order_config = {
    "wallet_address": "0x...",          # Required: Must match registered wallet
    "coin": "BTC",                      # Required: Cryptocurrency symbol
    "is_buy": True,                     # Required: Direction (true=long, false=short)
    "size": 0.01,                       # Required: Size in coin units
    "price": 77862.0,                   # Required: Price in USD
    "order_type": "market",             # Required: "market" or "limit"
    "slippage": 0.03,                   # Required: Max slippage tolerance (0.03 = 3%)
    "leverage": 1,                      # Optional: Leverage multiplier (1-20x)
}
```

### 4d. Nansen API Endpoint Configuration

```python
# Base URL for all Nansen Perp operations
NANSEN_BASE_URL = "https://api.nansen.ai/api/v1"

# Key endpoints
POST /perp/order              # Prepare order (returns EIP-712 for signing)
POST /perp/execute            # Execute signed order
GET  /perp/account            # Check account balance
GET  /perp/builder-fee        # Check approval status
POST /perp/approve-builder-fee# Request approval authorization
```

---

## 5. Wallet Creation & Registration Prerequisites

### Pre-Requisites Checklist

Before trading can work:

- [ ] **Nansen API Key Obtained**
  - Location: Nansen Account → API Keys
  - Format: `nsn_xxxxxxxxxxxxxxxx`
  - Action: Set `NANSEN_API_KEY` in `.env`

- [ ] **Hyperliquid Wallet Created**
  - Method: Any EVM wallet (MetaMask, Ledger, etc.)
  - Action: Save address as `PORTFOLIO_WALLET_HYPERLIQUID`
  - Verification: Address must start with `0x` and be 42 chars

- [ ] **Private Key Exported (Safely)**
  - ⚠️ WARNING: Never expose this key
  - Action: Export from wallet and save as `PORTFOLIO_WALLET_PRIVATE_KEY`
  - Storage: Only in `.env`, never in code or git

- [ ] **Wallet Registered with Nansen**
  - Method: Connect wallet on Nansen.ai website
  - Verification: List wallet in Nansen account settings

- [ ] **USDC Funded**
  - Amount: ≥ $1,000 recommended (depends on position size)
  - Location: Both Spot and Perpetuals balances
  - Source: Centralized exchange or bridge

- [ ] **Builder Fee Approved**
  - Method: One-time EIP-712 signature
  - Status: Check with `check_builder_fee_status()`
  - Action: Sign if not yet approved

- [ ] **Account Balance Verified**
  - Check: `get_account_balance()` returns correct USDC
  - Minimum: Enough for at least one trade

---

## 6. Prerequisites for Live Trading on Hyperliquid via Nansen

### Nansen-Specific Requirements

1. **API Authentication**
   ```python
   headers = {
       "apikey": NANSEN_API_KEY,
       "Content-Type": "application/json"
   }
   # Must include apikey header on EVERY request
   ```

2. **Wallet Connection**
   ```python
   # Nansen must have permission to trade with this wallet
   # Verify in Nansen dashboard → Connected Wallets
   wallet_address = os.getenv("PORTFOLIO_WALLET_HYPERLIQUID")
   ```

3. **Order Signing Capability**
   ```python
   # Must be able to sign EIP-712 messages
   # Requires access to private key
   private_key = os.getenv("PORTFOLIO_WALLET_PRIVATE_KEY")
   ```

### Hyperliquid-Specific Requirements

1. **Exchange Account Ready**
   - Account created on Hyperliquid
   - Minimum collateral deposited
   - Risk parameters configured

2. **Perpetuals Margin Available**
   ```python
   # Hyperliquid requires USDC in perpetuals wallet for margin
   balance_info = await trader.get_account_balance()
   total_margin = balance_info['total_usdc']  # Spot + Perps
   ```

3. **Leverage Settings Configured**
   ```python
   max_leverage = 20  # Set via env or code
   # Most trades use 1-10x, configurable per order
   ```

### Nansen Dashboard Prerequisites

- ✅ Wallet connected to your Nansen account
- ✅ Builder fee approved
- ✅ API key generated and active
- ✅ Wallet visible in "Connected Wallets" section

---

## 7. Error Handling & Initialization Code

### Health Check Function

```python
async def verify_nansen_wallet_ready():
    """Comprehensive wallet setup verification"""
    
    # 1. Check environment variables
    required_vars = [
        "NANSEN_API_KEY",
        "PORTFOLIO_WALLET_HYPERLIQUID", 
        "PORTFOLIO_WALLET_PRIVATE_KEY"
    ]
    
    for var in required_vars:
        if not os.getenv(var):
            raise ValueError(f"Missing {var} in environment")
    
    api_key = os.getenv("NANSEN_API_KEY")
    wallet = os.getenv("PORTFOLIO_WALLET_HYPERLIQUID")
    pk = os.getenv("PORTFOLIO_WALLET_PRIVATE_KEY")
    
    # 2. Validate wallet format
    if not wallet.startswith("0x") or len(wallet) != 42:
        raise ValueError(f"Invalid wallet address format: {wallet}")
    
    # 3. Verify private key matches wallet
    try:
        from eth_account import Account
        account = Account.from_key(pk)
        if account.address.lower() != wallet.lower():
            raise ValueError(
                f"Private key mismatch! "
                f"Expected {wallet}, got {account.address}"
            )
    except Exception as e:
        raise ValueError(f"Invalid private key: {e}")
    
    # 4. Check API connectivity
    async with aiohttp.ClientSession() as session:
        headers = {"apikey": api_key, "Content-Type": "application/json"}
        
        # Test health check
        try:
            async with session.get(
                "https://api.nansen.ai/api/v1/perp/account",
                params={"wallet_address": wallet},
                headers=headers,
                timeout=10
            ) as resp:
                if resp.status == 401:
                    raise ValueError("Invalid API key")
                if resp.status not in [200, 400]:  # 400 might be valid (no balance)
                    raise ValueError(f"API returned {resp.status}")
        except Exception as e:
            raise ValueError(f"API connection failed: {e}")
    
    # 5. Check builder fee approval
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.nansen.ai/api/v1/perp/builder-fee",
                params={"wallet_address": wallet},
                headers=headers
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if not data.get("approved"):
                        logger.warning("⚠️ Builder fee not approved yet")
                        logger.warning("   Run: python cli/approve_builder_fee.py")
    except Exception as e:
        logger.warning(f"Could not check builder fee: {e}")
    
    # 6. Check account balance
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.nansen.ai/api/v1/perp/account",
                params={"wallet_address": wallet},
                headers=headers
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    perp_balance = float(data.get("balance", 0))
                    spot_balance = float(data.get("spotUsdc", 0))
                    total = perp_balance + spot_balance
                    
                    logger.info(f"✅ Account balance: ${total:,.2f}")
                    
                    if total < 100:
                        logger.warning("⚠️ Low balance. Recommend ≥$1,000 for comfortable trading")
    except Exception as e:
        logger.warning(f"Could not check balance: {e}")
    
    return True
```

### Initialization Code Pattern

```python
from cryptoagents.exchanges import HyperliquidTrader

async def initialize_trader():
    """Initialize and verify Hyperliquid trader"""
    
    # Verify wallet setup
    await verify_nansen_wallet_ready()
    
    # Create trader instance
    trader = HyperliquidTrader(
        nansen_api_key=os.getenv("NANSEN_API_KEY"),
        wallet_address=os.getenv("PORTFOLIO_WALLET_HYPERLIQUID"),
        wallet_private_key=os.getenv("PORTFOLIO_WALLET_PRIVATE_KEY"),
        max_leverage=20
    )
    
    # Check all systems
    balance = await trader.get_account_balance()
    logger.info(f"Total margin available: ${balance['total_usdc']}")
    
    fee_status = await trader.check_builder_fee_status()
    if not fee_status.get("approved"):
        logger.error("❌ Builder fee not approved. Please approve first.")
        return None
    
    logger.info("✅ Trader initialized and ready")
    return trader
```

### Common Error Scenarios

| Error | Cause | Solution |
|-------|-------|----------|
| `Missing NANSEN_API_KEY` | Env var not set | Add to `.env` file |
| `Invalid API key` | Wrong key format | Regenerate from Nansen dashboard |
| `401 Unauthorized` | Incorrect API key | Verify key in `.env` |
| `Private key address mismatch` | Wrong wallet/key pair | Export correct private key |
| `Builder fee not approved` | One-time auth needed | Run `python cli/approve_builder_fee.py` |
| `Insufficient USDC` | Low balance | Deposit more USDC to wallet |
| `{"status": "500"}` | Server error | Verify EIP-712 signature format |

---

## 8. Security Best Practices

### ✅ DO:
- ✅ Keep private key in `.env` only
- ✅ Sign transactions locally on YOUR computer
- ✅ Use hardware wallet when possible
- ✅ Rotate API keys periodically
- ✅ Verify wallet address before signing
- ✅ Test with small trades first
- ✅ Monitor all transactions via Nansen dashboard

### ❌ DON'T:
- ❌ Put private key in code or version control
- ❌ Share API key publicly
- ❌ Use same API key in multiple environments
- ❌ Enable trading without approval verification
- ❌ Accept pre-signed payloads from untrusted sources
- ❌ Run trading bots on shared computers
- ❌ Store wallet data in databases

---

## 9. Summary Checklist

Before your agent can execute trades:

- [ ] NANSEN_API_KEY obtained and in `.env`
- [ ] PORTFOLIO_WALLET_HYPERLIQUID address in `.env`
- [ ] PORTFOLIO_WALLET_PRIVATE_KEY in `.env`
- [ ] Wallet registered with Nansen.ai
- [ ] Wallet funded with USDC (both Spot & Perps)
- [ ] Private key verified against wallet
- [ ] API connectivity tested
- [ ] Builder fee approved (one-time)
- [ ] Account balance ≥ $1,000
- [ ] Health check passed: `verify_nansen_wallet_ready()`
- [ ] Trader instance initialized: `HyperliquidTrader(...)`
- [ ] Ready for trading! 🚀

---

## References

- **Nansen API Docs**: https://docs.nansen.ai/
- **Hyperliquid Integration**: See `HYPERLIQUID_INTEGRATION.md`
- **Quick Approval**: See `APPROVAL_QUICK_START.md`

