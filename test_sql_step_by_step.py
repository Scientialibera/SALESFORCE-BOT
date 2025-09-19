#!/usr/bin/env python3
"""
Step-by-step SQL agent testing to identify and fix issues.
"""
import asyncio
import json
import aiohttp
import os
from dotenv import load_dotenv

# Load environment
load_dotenv()

async def test_sql_agent_step_by_step():
    """Test SQL agent execution step by step"""
    
    print("🔍 Step-by-step SQL Agent Testing")
    print("=" * 50)
    
    # Test 1: Basic connectivity
    print("\n1. Testing basic API connectivity...")
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get("http://localhost:8004/health") as response:
                if response.status == 200:
                    print("✅ API is responsive")
                else:
                    print(f"❌ Health check failed: {response.status}")
                    return
        except Exception as e:
            print(f"❌ Cannot connect to API: {e}")
            return
    
    # Test 2: SQL-specific query
    print("\n2. Testing SQL agent with sales query...")
    request_data = {
        "messages": [
            {
                "role": "user",
                "content": "Show me sales revenue for this quarter"
            }
        ],
        "user_id": "test_user",
        "session_id": "sql_test_session",
        "metadata": {}
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                "http://localhost:8004/api/chat",
                json=request_data,
                headers={"Content-Type": "application/json"}
            ) as response:
                print(f"Response status: {response.status}")
                
                if response.status == 200:
                    result = await response.json()
                    print("✅ Request successful")
                    print(f"Response keys: {list(result.keys())}")
                    
                    if "choices" in result and result["choices"]:
                        message = result["choices"][0]["message"]
                        response_text = message["content"]
                        print(f"Response length: {len(response_text)}")
                        print(f"Response preview: {response_text[:200]}...")
                        
                        # Check if it looks like SQL was executed
                        if any(word in response_text.lower() for word in ["sql", "query", "data", "revenue", "sales"]):
                            print("✅ Response contains SQL/data-related content")
                        else:
                            print("⚠️  Response may not be from SQL agent")
                            
                        if "wasn't able to process" in response_text.lower():
                            print("❌ Agent execution failed")
                        else:
                            print("✅ Agent execution appears successful")
                    
                    # Check usage
                    if "usage" in result:
                        usage = result["usage"]
                        print(f"Usage: {json.dumps(usage, indent=2)}")
                        
                else:
                    text = await response.text()
                    print(f"❌ Request failed: {text}")
                    
        except Exception as e:
            print(f"❌ Request exception: {e}")
    
    # Test 3: Different SQL query types
    print("\n3. Testing different SQL query patterns...")
    queries = [
        "What are the top opportunities?",
        "Show me account performance",
        "Get sales data for this month"
    ]
    
    for i, query in enumerate(queries, 1):
        print(f"\n  3.{i} Testing: '{query}'")
        request_data = {
            "messages": [
                {
                    "role": "user",
                    "content": query
                }
            ],
            "user_id": "test_user",
            "session_id": f"sql_test_pattern_{i}",
            "metadata": {}
        }
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(
                    "http://localhost:8004/api/chat",
                    json=request_data,
                    headers={"Content-Type": "application/json"}
                ) as response:
                    if response.status == 200:
                        result = await response.json()
                        if "choices" in result and result["choices"]:
                            response_text = result["choices"][0]["message"]["content"]
                        
                            if "wasn't able to process" in response_text.lower():
                                print(f"    ❌ Failed: {response_text[:100]}...")
                            else:
                                print(f"    ✅ Success: {response_text[:100]}...")
                        else:
                            print("    ❌ No choices in response")
                    else:
                        print(f"    ❌ HTTP {response.status}")
                        
            except Exception as e:
                print(f"    ❌ Exception: {e}")

if __name__ == "__main__":
    asyncio.run(test_sql_agent_step_by_step())