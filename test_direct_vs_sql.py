#!/usr/bin/env python3
"""
Test direct answers vs SQL answers to debug the difference
"""
import asyncio
import json
import aiohttp

async def test_direct_vs_sql():
    """Test both direct and SQL answers to see the difference"""
    
    print("🧪 Testing Direct Answer vs SQL Answer")
    print("=" * 60)
    
    # Test 1: Direct answer query (should work)
    print("\n1️⃣ Testing DIRECT answer query...")
    direct_request = {
        "messages": [
            {
                "role": "user",
                "content": "Hello, what can you help me with?"
            }
        ],
        "user_id": "test_user",
        "session_id": "direct_test_session",
        "metadata": {}
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                "http://localhost:8004/api/chat",
                json=direct_request,
                headers={"Content-Type": "application/json"}
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    message = result["choices"][0]["message"]["content"]
                    metadata = result.get("metadata", {})
                    
                    print(f"✅ Direct answer SUCCESS")
                    print(f"📝 Response: {message[:100]}...")
                    print(f"📊 Plan type: {metadata.get('plan_type', 'unknown')}")
                    print(f"📊 Execution status: {metadata.get('execution_status', 'unknown')}")
                else:
                    print(f"❌ Direct answer FAILED: {response.status}")
        except Exception as e:
            print(f"❌ Direct answer EXCEPTION: {e}")
    
    print("\n" + "-" * 60)
    
    # Test 2: SQL answer query (currently failing)
    print("\n2️⃣ Testing SQL answer query...")
    sql_request = {
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
                json=sql_request,
                headers={"Content-Type": "application/json"}
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    message = result["choices"][0]["message"]["content"]
                    metadata = result.get("metadata", {})
                    
                    if "wasn't able to process" in message.lower():
                        print(f"❌ SQL answer FAILED")
                    else:
                        print(f"✅ SQL answer SUCCESS")
                    
                    print(f"📝 Response: {message[:100]}...")
                    print(f"📊 Plan type: {metadata.get('plan_type', 'unknown')}")
                    print(f"📊 Execution status: {metadata.get('execution_status', 'unknown')}")
                    print(f"📊 Steps executed: {metadata.get('steps_executed', 'unknown')}")
                    
                    if metadata.get('execution_status') == 'failed':
                        print(f"🔍 Check server logs for 'Function not found' errors")
                else:
                    print(f"❌ SQL answer FAILED: {response.status}")
        except Exception as e:
            print(f"❌ SQL answer EXCEPTION: {e}")
    
    print("\n" + "=" * 60)
    print("🔍 Now check the server terminal for detailed logs!")
    print("Look for:")
    print("  - 'Function not found - debugging available functions'")
    print("  - Available plugins and functions list")
    print("  - Any kernel plugin registration errors")

if __name__ == "__main__":
    asyncio.run(test_direct_vs_sql())