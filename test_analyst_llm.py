#!/usr/bin/env python3
"""Test script to verify analysts call OpenRouter LLM"""

import asyncio
import os
from dotenv import load_dotenv
from cryptoagents.agents.blockchain_analyst import BlockchainAnalyst
from cryptoagents.agents.sentiment_analyst import SentimentAnalyst
from cryptoagents.agents.technical_analyst import TechnicalAnalyst
from cryptoagents.agents.macro_analyst import MacroAnalyst
from cryptoagents.agents.fundamental_analyst import FundamentalAnalyst
from cryptoagents.llm_clients import create_llm_client

load_dotenv()

async def test_analysts():
    """Test all analysts with LLM client"""
    
    # Initialize LLM client
    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    if not openrouter_key:
        print("[ERROR] OPENROUTER_API_KEY not set")
        return
    
    print("[INFO] Initializing LLM client with OpenRouter...")
    llm_factory = create_llm_client(
        provider="openrouter",
        model="gpt-4o",
        api_key=openrouter_key,
        temperature=0.7,
        max_tokens=300
    )
    llm_client = llm_factory.get_llm()
    
    # Sample market data
    market_data = {
        "current_price": 45000,
        "market_cap": 900000000000,
        "volume_24h": 25000000000,
        "price_change_24h": 2.5,
        "market_cap_rank": 1,
        "circulating_supply": 21000000,
        "fully_diluted_valuation": 950000000000,
    }
    
    # Test each analyst
    analysts = [
        ("Blockchain", BlockchainAnalyst(nansen_api=None, llm_client=llm_client)),
        ("Sentiment", SentimentAnalyst(llm_client=llm_client)),
        ("Technical", TechnicalAnalyst(llm_client=llm_client)),
        ("Macro", MacroAnalyst(coingecko_api=None, llm_client=llm_client)),
        ("Fundamental", FundamentalAnalyst(llm_client=llm_client)),
    ]
    
    print("\n" + "="*60)
    print("Testing Analysts with OpenRouter LLM")
    print("="*60 + "\n")
    
    for name, analyst in analysts:
        try:
            print(f"[TEST] {name} Analyst...")
            result = await analyst.analyze("BTC", market_data)
            
            print(f"  [OK] Analysis completed")
            print(f"      Score: {result.score:.2f}")
            print(f"      Confidence: {result.confidence:.2f}")
            print(f"      Reasoning: {result.reasoning[:100]}...")
            print()
            
        except Exception as e:
            print(f"  [ERROR] {name} analyst failed: {e}\n")
    
    print("="*60)
    print("✅ All analysts tested!")
    print("="*60)

if __name__ == "__main__":
    asyncio.run(test_analysts())
