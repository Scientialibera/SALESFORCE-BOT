#!/usr/bin/env python3
"""Test various message types with the chat API."""

import requests
import json

def test_message(message, description):
    """Test a single message."""
    print(f"\n=== Testing: {description} ===")
    print(f"Message: {message}")
    
    url = "http://localhost:8004/api/chat"
    data = {
        "messages": [{"role": "user", "content": message}],
        "user_id": "test_user",
        "session_id": "test_session_various"
    }
    
    try:
        response = requests.post(url, json=data, timeout=30)
        print(f"Status: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            assistant_message = result["choices"][0]["message"]["content"]
            print(f"✅ SUCCESS")
            print(f"Response: {assistant_message}")
            print(f"Turn ID: {result.get('turn_id', 'N/A')}")
            print(f"Usage: {result.get('usage', {})}")
        else:
            print(f"❌ FAILED: {response.text}")
            
    except Exception as e:
        print(f"❌ ERROR: {e}")

if __name__ == "__main__":
    print("Testing various message types...")
    
    # Test cases
    test_cases = [
        ("Hello, how are you?", "Basic greeting"),
        ("What's the weather like?", "Unrelated question"),
        ("Show me sales data for Q3", "SQL-related query"),
        ("Who are the key contacts at Acme Corp?", "Graph/relationship query"),
        ("", "Empty message"),
        ("A" * 1000, "Very long message"),
        ("What's 2+2?", "Simple calculation"),
        ("Tell me about Salesforce opportunities", "Mixed SQL/Graph query")
    ]
    
    for message, description in test_cases:
        test_message(message, description)
    
    print("\n=== Test Summary ===")
    print("All test cases completed. Check responses above for any issues.")