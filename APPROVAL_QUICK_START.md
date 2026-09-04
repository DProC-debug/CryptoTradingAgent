# Builder Fee Approval - Quick Start

## What Is This?

Before your agent can place orders on Hyperliquid, you must approve the builder fee. This is a **one-time** security authorization.

You **do NOT** share your private key with the agent. You sign locally on your computer.

---

## Quick Steps

### 1. Start Your Agent
```bash
python cli/autonomous_trader.py
```

The agent will check approval and tell you if it's needed.

### 2. If Approval Needed

The agent will output the **EIP712 payload**. Copy it.

### 3. Sign Locally

**Option A: Using the helper script (Recommended)**
```bash
# Install dependencies first
pip install eth-account

# Sign the payload (paste when prompted)
python cli/sign_eip712.py YOUR_PRIVATE_KEY
# Then paste the EIP712 payload and press Ctrl+D
```

**Option B: Using MetaMask**
1. Open MetaMask
2. Account → Sign Message
3. Paste the EIP712 payload
4. Click Sign

### 4. You Get Signature

The script or MetaMask will give you:
```json
{
  "r": "0x...",
  "s": "0x...",
  "v": 27
}
```

### 5. Execute Approval

Use the `HyperliquidTrader.execute_approval_with_signature()` method in your code:

```python
success = await trader.execute_approval_with_signature(
    action=approval_data["action"],
    nonce=approval_data["nonce"],
    signature={
        "r": "0x...",
        "s": "0x...",
        "v": 27
    }
)
```

Or use curl:
```bash
curl -X POST "https://api.nansen.ai/api/v1/perp/execute" \
  -H "apikey: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "action": {...},
    "nonce": 1234567890000,
    "signature": {"r": "0x...", "s": "0x...", "v": 27}
  }'
```

### 6. Done! Ready to Trade

After approval executes successfully, restart your agent and it will start trading!

---

## Security Important

🔒 **Never do this:**
- ❌ Put your private key in `.env`
- ❌ Share your private key
- ❌ Use private key on untrusted computers
- ❌ Paste private key in web forms

✅ **Always do this:**
- ✅ Sign locally on YOUR computer
- ✅ Use a hardware wallet if possible
- ✅ Verify wallet address before signing
- ✅ Keep private key completely private

---

## Automatic Check in Agent

The agent automatically checks approval at startup:

```
START
  ↓
CHECK BUILDER FEE STATUS
  ├─ Already Approved? → START TRADING
  └─ Not Approved?
      ├─ Output EIP712 payload
      ├─ Ask you to sign locally
      ├─ Wait for you to provide signature
      ├─ Execute approval with your signature
      └─ START TRADING
```

---

## Detailed Guide

See `BUILDER_FEE_APPROVAL.md` for:
- Complete API documentation
- Multiple signing methods
- Troubleshooting
- Full technical details
