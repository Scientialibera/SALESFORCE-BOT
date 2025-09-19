#!/usr/bin/env python3
"""Test the full agent system with different query types."""

import requests
import json
import time

def test_query(query, description, expected_agent_type=None):
    """Test a single query and analyze the response."""
    print(f"\n{'='*60}")
    print(f"TEST: {description}")
    print(f"QUERY: {query}")
    print(f"EXPECTED AGENT: {expected_agent_type or 'Any'}")
    print('='*60)
    
    url = "http://localhost:8004/api/chat"
    data = {
        "messages": [{"role": "user", "content": query}],
        "user_id": "test_user",
        "session_id": f"test_session_{int(time.time())}"  # Unique session per test
    }
    
    try:
        start_time = time.time()
        response = requests.post(url, json=data, timeout=60)
        end_time = time.time()
        
        print(f"Response Time: {end_time - start_time:.2f} seconds")
        print(f"Status Code: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            assistant_message = result["choices"][0]["message"]["content"]
            metadata = result.get("metadata", {})
            
            print(f"✅ SUCCESS")
            print(f"Response: {assistant_message}")
            print(f"Session ID: {result.get('session_id', 'N/A')}")
            print(f"Turn ID: {result.get('turn_id', 'N/A')}")
            
            # Analyze metadata
            print(f"\nMETADATA ANALYSIS:")
            print(f"  Mode: {metadata.get('mode', 'N/A')}")
            print(f"  Plan Type: {metadata.get('plan_type', 'N/A')}")
            print(f"  Plan ID: {metadata.get('plan_id', 'N/A')}")
            print(f"  Execution Status: {metadata.get('execution_status', 'N/A')}")
            print(f"  Steps Executed: {metadata.get('steps_executed', 'N/A')}")
            
            # Usage stats
            usage = result.get("usage", {})
            print(f"\nUSAGE STATS:")
            print(f"  Prompt Tokens: {usage.get('prompt_tokens', 'N/A')}")
            print(f"  Completion Tokens: {usage.get('completion_tokens', 'N/A')}")
            print(f"  Total Tokens: {usage.get('total_tokens', 'N/A')}")
            
            # Sources
            sources = result.get("sources", [])
            print(f"\nSOURCES: {len(sources)} found")
            for i, source in enumerate(sources[:3]):  # Show first 3
                print(f"  [{i+1}] {source}")
                
            return True
        else:
            print(f"❌ FAILED")
            print(f"Error: {response.text}")
            return False
            
    except Exception as e:
        print(f"❌ EXCEPTION: {e}")
        return False

def main():
    """Run comprehensive agent system tests."""
    print("🚀 STARTING COMPREHENSIVE AGENT SYSTEM TESTS")
    print("=" * 80)
    
    test_cases = [
        # Basic functionality tests
        ("Hello, how are you?", "Basic greeting (should use simple agent)", "simple"),
        ("What can you help me with?", "Capability inquiry", "simple"),
        
        # SQL agent tests
        ("Show me sales data for Q3 2024", "SQL query - sales data", "sql"),
        ("What are the top performing products?", "SQL query - product performance", "sql"),
        ("How many opportunities do we have this quarter?", "SQL query - opportunity count", "sql"),
        
        # Graph agent tests  
        ("Who are the key contacts at Acme Corporation?", "Graph query - account contacts", "graph"),
        ("Show me the relationship between John Smith and Microsoft", "Graph query - relationships", "graph"),
        ("What accounts is Sarah Johnson associated with?", "Graph query - contact accounts", "graph"),
        
        # Hybrid/complex queries
        ("Show me sales data for accounts where John Smith is the primary contact", "Hybrid query - SQL + Graph", "hybrid"),
        ("What are the revenue numbers for all accounts managed by our top contacts?", "Complex hybrid query", "hybrid"),
        
        # Account resolution tests
        ("Show me information about Acme Corp", "Account resolution test", "account_resolution"),
        ("What's the status of Microsoft deals?", "Account resolution + SQL", "hybrid"),
        
        # Edge cases
        ("", "Empty query", "error"),
        ("asdfghjkl qwerty", "Nonsense query", "simple"),
        ("What's the weather in New York?", "Unrelated query", "simple")
    ]
    
    successful_tests = 0
    total_tests = len(test_cases)
    
    for query, description, expected_agent in test_cases:
        try:
            success = test_query(query, description, expected_agent)
            if success:
                successful_tests += 1
        except KeyboardInterrupt:
            print("\n⏹️ Tests interrupted by user")
            break
        except Exception as e:
            print(f"❌ Test failed with exception: {e}")
        
        # Small delay between tests
        time.sleep(1)
    
    print(f"\n{'='*80}")
    print(f"🏁 TEST SUMMARY")
    print(f"{'='*80}")
    print(f"Total Tests: {total_tests}")
    print(f"Successful: {successful_tests}")
    print(f"Failed: {total_tests - successful_tests}")
    print(f"Success Rate: {(successful_tests/total_tests)*100:.1f}%")
    
    if successful_tests == total_tests:
        print("🎉 ALL TESTS PASSED! The agent system is working correctly.")
    elif successful_tests > total_tests * 0.8:
        print("✅ Most tests passed. Minor issues may need attention.")
    else:
        print("⚠️ Multiple tests failed. The agent system needs debugging.")

if __name__ == "__main__":
    main()