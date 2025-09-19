#!/usr/bin/env python3
"""
Simple SQL agent test with one focused query
"""
import asyncio
import json
import aiohttp

async def test_single_sql_query():
    """Test a single SQL query to debug issues"""
    
    print("🔍 Testing single SQL query: 'Show me sales revenue'")
    print("📝 Check the server terminal for detailed logs")
    print("=" * 60)
    
    request_data = {
        "messages": [
            {
                "role": "user",
                "content": "Show me sales revenue for this quarter"
            }
        ],
        "user_id": "test_user_sql",
        "session_id": "debug_sql_session",
        "metadata": {}
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            print("📤 Sending request...")
            async with session.post(
                "http://localhost:8004/api/chat",
                json=request_data,
                headers={"Content-Type": "application/json"}
            ) as response:
                print(f"📥 Response status: {response.status}")
                
                if response.status == 200:
                    result = await response.json()
                    
                    if "choices" in result and result["choices"]:
                        message = result["choices"][0]["message"]
                        response_text = message["content"]
                        
                        print(f"💬 Response: {response_text}")
                        print(f"📊 Usage: {result.get('usage', {})}")
                        print(f"📋 Metadata: {result.get('metadata', {})}")
                        
                        if "wasn't able to process" in response_text.lower():
                            print("\n❌ SQL Agent execution failed!")
                            print("🔍 Check server logs for:")
                            print("   - 'Function not found: sql_agent'")
                            print("   - 'Step execution failed'")
                            print("   - 'SQL agent execution failed'")
                        else:
                            print("\n✅ SQL Agent appears to be working!")
                            
                else:
                    text = await response.text()
                    print(f"❌ Request failed: {text}")
                    
        except Exception as e:
            print(f"❌ Exception: {e}")

if __name__ == "__main__":
    asyncio.run(test_single_sql_query())