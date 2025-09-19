#!/usr/bin/env python3
"""
Test the chat endpoint with a simple response bypass to isolate issues.
"""
import requests
import json

def test_simple_response():
    url = "http://localhost:8004/api/chat"
    
    # Simple test data
    data = {
        "messages": [
            {
                "role": "user", 
                "content": "Hello"
            }
        ],
        "user_id": "test_user"
    }
    
    try:
        print("Testing with minimal request...")
        response = requests.post(url, json=data)
        print(f"Status: {response.status_code}")
        
        if response.status_code == 500:
            print("500 error - checking for specific error details")
            print(f"Response: {response.text}")
        elif response.headers.get('content-type', '').startswith('application/json'):
            print(f"Response: {json.dumps(response.json(), indent=2)}")
        else:
            print(f"Response: {response.text}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_simple_response()