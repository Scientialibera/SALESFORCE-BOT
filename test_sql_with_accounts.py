#!/usr/bin/env python3
"""
Test SQL agent with dummy account data for resolution testing.

This script tests the SQL agent functionality with sample account names
that would be found in the query to ensure account resolution works properly.
"""

import asyncio
import aiohttp
import json
from typing import Dict, Any

async def test_sql_agent_with_accounts():
    """Test SQL agent with various account-based queries."""
    
    base_url = "http://localhost:8004"
    
    # Test cases with different account mentions
    test_cases = [
        {
            "name": "Generic revenue query (should work with any detected accounts)",
            "query": "Show me sales revenue for this quarter",
            "session_id": "test_revenue_session"
        },
        {
            "name": "Microsoft revenue query",
            "query": "What is the sales revenue for Microsoft this quarter?",
            "session_id": "test_microsoft_session"
        },
        {
            "name": "Apple opportunities query", 
            "query": "Show me open opportunities for Apple",
            "session_id": "test_apple_session"
        },
        {
            "name": "Google and Amazon comparison",
            "query": "Compare revenue between Google and Amazon for this year",
            "session_id": "test_comparison_session"
        }
    ]
    
    async with aiohttp.ClientSession() as session:
        print("🔍 Testing SQL Agent with Account Resolution")
        print("=" * 60)
        
        for i, test_case in enumerate(test_cases, 1):
            print(f"\n📋 Test {i}: {test_case['name']}")
            print(f"📤 Query: '{test_case['query']}'")
            print("-" * 40)
            
            # Prepare the request
            request_data = {
                "messages": [
                    {
                        "role": "user",
                        "content": test_case["query"]
                    }
                ],
                "user_id": "test_user_accounts",
                "session_id": test_case["session_id"],
                "metadata": {}
            }
            
            try:
                # Send request
                async with session.post(
                    f"{base_url}/api/chat",
                    json=request_data,
                    headers={"Content-Type": "application/json"}
                ) as response:
                    
                    if response.status == 200:
                        result = await response.json()
                        
                        # Parse response
                        assistant_response = result.get("choices", [{}])[0].get("message", {}).get("content", "No response")
                        usage = result.get("usage", {})
                        metadata = result.get("metadata", {})
                        
                        print(f"✅ Status: {response.status}")
                        print(f"💬 Response: {assistant_response[:200]}...")
                        print(f"📊 Tokens: {usage.get('total_tokens', 'Unknown')}")
                        print(f"🔧 Plan Type: {metadata.get('plan_type', 'Unknown')}")
                        print(f"🎯 Execution: {metadata.get('execution_status', 'Unknown')}")
                        
                        # Check if it's an SQL agent response
                        if metadata.get('plan_type') == 'sql_only':
                            if 'success' in assistant_response:
                                try:
                                    response_json = json.loads(assistant_response)
                                    if response_json.get('success'):
                                        print("🎉 SQL agent executed successfully!")
                                    else:
                                        print(f"⚠️  SQL agent error: {response_json.get('error', 'Unknown error')}")
                                except json.JSONDecodeError:
                                    print("📝 Response is not JSON (might be direct answer)")
                            else:
                                print("📝 Got direct text response")
                        else:
                            print(f"ℹ️  Non-SQL plan type: {metadata.get('plan_type')}")
                            
                    else:
                        print(f"❌ Request failed with status: {response.status}")
                        error_text = await response.text()
                        print(f"📝 Error: {error_text[:200]}...")
                        
            except Exception as e:
                print(f"❌ Request failed with exception: {str(e)}")
            
            if i < len(test_cases):
                print("\n⏳ Waiting 2 seconds before next test...")
                await asyncio.sleep(2)

if __name__ == "__main__":
    print("🚀 Starting SQL Agent Account Resolution Tests")
    print("📝 Make sure the chatbot server is running on http://localhost:8004")
    print("🔍 These tests will check account resolution and SQL agent execution")
    print()
    
    asyncio.run(test_sql_agent_with_accounts())