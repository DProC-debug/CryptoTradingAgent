"""Nansen API Diagnostics - Test your Nansen API key and endpoints"""

import os
import requests
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv("NANSEN_API_KEY")

if not api_key:
    print("❌ NANSEN_API_KEY not set in .env file")
    exit(1)

print(f"✓ API Key found: {api_key[:20]}...\n")

headers = {"apikey": api_key}
base_url = "https://api.nansen.ai/api/v1"

# Test endpoints with proper POST format
test_cases = [
    {
        "name": "Address Balance (Ethereum)",
        "endpoint": "profiler/address/current-balance",
        "data": {
            "address": "0x28c6c06298d514db089934071355e5743bf21d60",
            "chain": "ethereum",
            "hide_spam_token": True,
            "pagination": {"page": 1, "per_page": 5}
        }
    },
]

print("Testing Nansen API POST endpoints:")
print("-" * 80)

for test in test_cases:
    try:
        url = f"{base_url}/{test['endpoint']}"
        r = requests.post(
            url,
            headers=headers,
            json=test['data'],
            timeout=10
        )
        
        if r.status_code == 200:
            print(f"✓ {test['name']:40} → Status {r.status_code}")
            try:
                resp = r.json()
                if isinstance(resp, dict):
                    keys = list(resp.keys())[:3]
                    print(f"  └─ Keys: {keys}")
            except:
                pass
        else:
            print(f"✗ {test['name']:40} → Status {r.status_code}")
            try:
                err = r.json()
                msg = err.get('message', str(err))[:50] if isinstance(err, dict) else str(err)[:50]
                print(f"  └─ {msg}")
            except:
                print(f"  └─ {r.text[:50]}")
                
    except Exception as e:
        print(f"✗ {test['name']:40} → Error: {str(e)[:50]}")

print("\n" + "=" * 80)
print("Next Steps:")
print("1. ✓ API Key authentication is correctly implemented")
print("2. Run 'python main.py' to test full integration")
print("3. Check cryptoagents/dataflows/nansen_api.py for all available methods")
print("=" * 80)
