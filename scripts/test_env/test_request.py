#!/usr/bin/env python3
"""
Simple test to debug server issues.
"""

import requests
import json

def test_server():
    url = "http://localhost:8000/api/v1/chat"
    headers = {"Content-Type": "application/json"}
    data = {
        "messages": [
            {"role": "user", "content": "Accounts that have SOWs similar to Microsoft's AI Chatbot engagements (i think the offer name is ai_chatbot) and then a way to contact the related account contacts"}
        ],
        "user_id": "test-user",
        "session_id": "test-session-sql"
    }
    
    try:
        print("Making request...")
        response = requests.post(url, headers=headers, json=data, timeout=30)
        print(f"Status code: {response.status_code}")
        print(f"Response: {response.text}")
    except Exception as e:
        print(f"Request failed: {e}")

if __name__ == "__main__":
    test_server()