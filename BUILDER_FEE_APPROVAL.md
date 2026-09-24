# Builder Fee Approval Flow for Hyperliquid Trading

## Overview

Before placing any orders on Hyperliquid, you must approve the builder fee. This is a one-time process that uses EIP712 signing.

**Important:** You never share your private key with the agent. You sign locally and provide the signature.

---

## The 3-Step Process

```
┌────────────┐   unsigned action    ┌──────────┐   {r,s,v}    ┌───────────────┐
│  prepare   │ ───────────────────► │   sign   │ ───────────► │    execute    │
│ (6 routes) │      + eip712        │ (local)  │              │ (1 route)     │
└────────────┘                      └──────────┘              └───────────────┘
     no state change                  your keys                  real money
```

### Step 1: Check Status
```bash
curl -s "https://api.nansen.ai/api/v1/perp/builder-fee?wallet_address=0xYourWallet" \
  -H "apikey: YOUR_API_KEY"
```

**Response:**
```json
{
  "approved": false,
  "max_fee_rate": 0,
  "required_fee": 80,
  "builder_address": "0x1234..."
}
```

If `"approved": true`, you're done! Skip to trading.

### Step 2: Request Approval (Get EIP712 Payload)
```bash
curl -s -X POST "https://api.nansen.ai/api/v1/perp/approve-builder-fee" \
  -H "apikey: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"wallet_address": "0xYourWallet"}'
```

**Response:**
```json
{
  "action": {
    "wallet": "0xYourWallet",
    "fee_rate": 80,
    "builder_address": "0x1234...",
    "operation": "approve_builder_fee"
  },
  "eip712": {
    "types": {...},
    "primaryType": "ApproveBuilderFee",
    "domain": {...},
    "message": {...}
  },
  "nonce": 1754476800000
}
```

### Step 3: Sign Locally & Execute

**Option A: Using the Helper Script**
```bash
# 1. Save the EIP712 payload to a file
echo '{"types": {...}, ...}' > payload.json

# 2. Run the signing script (requires eth-account)
python cli/sign_eip712.py payload.json
```

**Option B: Using MetaMask**
1. Open MetaMask
2. Go to Account → Sign Message
3. Paste the EIP712 payload
4. Sign it
5. Copy the signature

**Option C: Using Python Directly**
```python
from eth_account.messages import encode_structured_data
from eth_account import Account

# Your EIP712 payload
eip712_payload = {...}  # From step 2

# Your private key (never share!)
account = Account.from_key("0x...")

# Sign
message = encode_structured_data(eip712_payload)
signed = account.sign_message(message)

# Extract signature
signature = {
    "r": hex(signed.r),
    "s": hex(signed.s),
    "v": signed.v
}
print(signature)
```

### Step 4: Execute the Approval
```bash
curl -s -X POST "https://api.nansen.ai/api/v1/perp/execute" \
  -H "apikey: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "action": {...},  # From step 2
    "nonce": 1754476800000,  # From step 2
    "signature": {
      "r": "0x...",
      "s": "0x...",
      "v": 27
    }
  }'
```

---

## Using with the Trading Agent

### Automatic Check
When you start the agent and it detects approval is needed:

1. **Agent logs the EIP712 payload**
   ```
   [ACTION REQUIRED] Sign the EIP712 message:
   EIP712 Payload:
   {...}
   ```

2. **You sign locally** (using script, MetaMask, or Python)
   ```bash
   python cli/sign_eip712.py payload.json
   ```

3. **You provide signature to agent**
   ```python
   trader = HyperliquidTrader(api_key, wallet)
   
   # After signing, execute the approval
   success = await trader.execute_approval_with_signature(
       action=approval["action"],
       nonce=approval["nonce"],
       signature={
           "r": "0x...",  # From your signing
           "s": "0x...",
           "v": 27
       }
   )
   ```

4. **Agent confirms approval**
   ```
   [OK] Builder fee approval executed successfully
   [OK] Ready to trade!
   ```

---

## Important Security Notes

⚠️ **NEVER:**
- Put your private key in `.env` files
- Share your private key with anyone
- Post your private key in logs
- Use your private key on untrusted computers

✅ **ALWAYS:**
- Sign locally on your own computer
- Keep your private key secure
- Use a hardware wallet if possible
- Verify the wallet address before signing

---

## Installation Requirements

```bash
pip install eth-account
```

---

## Troubleshooting

### "Can't find eth-account"
```bash
pip install eth-account
```

### "Invalid signature"
- Make sure you signed the correct EIP712 payload
- Verify the private key is correct
- Check that r, s, v values are formatted correctly (hex strings)

### "Approval already executed"
You can only approve once. If you already approved, you can now trade!

---

## Full Trading Flow

```
START AGENT
   ↓
CHECK APPROVAL STATUS
   ├─ If approved → Start trading
   └─ If not approved:
      ├─ Request approval payload
      ├─ Wait for you to sign locally
      ├─ You execute with signature
      └─ Start trading
```

Once approved, you won't need to sign again. The approval is permanent on your wallet!
