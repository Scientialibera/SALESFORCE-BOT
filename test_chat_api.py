#!/usr/bin/env python3
"""
Simple test script for the OpenAI-compatible chat API.
"""
import requests
import json

def test_chat_api():
    url = "http://localhost:8004/api/chat"
    
    # Test data in OpenAI Chat Completion format
    data = {
        "messages": [
            {
                "role": "user",
                "content": "Hello, how are you?"
            }
        ],
        "user_id": "test_user",
        "session_id": "test_session_123"
    }
    
    headers = {
        "Content-Type": "application/json"
    }
    
    try:
        print("Testing OpenAI-compatible chat endpoint...")
        print(f"URL: {url}")
        print(f"Request data: {json.dumps(data, indent=2)}")
        
        response = requests.post(url, json=data, headers=headers)
        
        print(f"\nResponse status: {response.status_code}")
        print(f"Response headers: {dict(response.headers)}")
        
        if response.headers.get('content-type', '').startswith('application/json'):
            try:
                response_data = response.json()
                print(f"Response data: {json.dumps(response_data, indent=2)}")
            except json.JSONDecodeError:
                print(f"Response text: {response.text}")
        else:
            print(f"Response text: {response.text}")
            
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")

if __name__ == "__main__":
    test_chat_api()