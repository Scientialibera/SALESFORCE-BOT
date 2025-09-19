#!/usr/bin/env python3
"""
Test script with detailed error handling.
"""
import requests
import json
import traceback

def test_with_error_details():
    url = "http://localhost:8004/api/chat"
    
    data = {
        "messages": [{"role": "user", "content": "Hello"}],
        "user_id": "test_user"
    }
    
    try:
        response = requests.post(url, json=data, timeout=30)
        print(f"Status: {response.status_code}")
        print(f"Headers: {dict(response.headers)}")
        
        # Try to get JSON response
        try:
            response_json = response.json()
            print(f"JSON Response: {json.dumps(response_json, indent=2)}")
        except:
            print(f"Raw Response: {response.text}")
            
    except Exception as e:
        print(f"Request error: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    test_with_error_details()