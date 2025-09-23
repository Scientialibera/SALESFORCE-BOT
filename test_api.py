#!/usr/bin/env python3

import requests
import json

def test_direct_answer():
    """Test direct answer scenario"""
    url = "http://localhost:8000/api/chat"
    payload = {
        "messages": [{"role": "user", "content": "Hello, how are you?"}],
        "user_id": "test@example.com"
    }

    try:
        response = requests.post(url, json=payload, timeout=30)
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text}")

        if response.status_code == 200:
            data = response.json()
            print("Success! Direct answer test passed")
            print(f"Assistant response: {data['choices'][0]['message']['content']}")
        else:
            print(f"Error: {response.status_code} - {response.text}")

    except Exception as e:
        print(f"Test failed with exception: {e}")

def test_sql_agent():
    """Test SQL agent scenario"""
    url = "http://localhost:8000/api/chat"
    payload = {
        "messages": [{"role": "user", "content": "Show me opportunities for Salesforce Inc"}],
        "user_id": "test@example.com"
    }

    try:
        response = requests.post(url, json=payload, timeout=30)
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text}")

        if response.status_code == 200:
            data = response.json()
            print("Success! SQL agent test passed")
            print(f"Assistant response: {data['choices'][0]['message']['content']}")
        else:
            print(f"Error: {response.status_code} - {response.text}")

    except Exception as e:
        print(f"Test failed with exception: {e}")

def test_graph_agent():
    """Test Graph agent scenario"""
    url = "http://localhost:8000/api/chat"
    payload = {
        "messages": [{"role": "user", "content": "What relationships does Microsoft Corporation have?"}],
        "user_id": "test@example.com"
    }

    try:
        response = requests.post(url, json=payload, timeout=30)
        print(f"Status Code: {response.status_code}")
        print(f"Response: {response.text}")

        if response.status_code == 200:
            data = response.json()
            print("Success! Graph agent test passed")
            print(f"Assistant response: {data['choices'][0]['message']['content']}")
        else:
            print(f"Error: {response.status_code} - {response.text}")

    except Exception as e:
        print(f"Test failed with exception: {e}")

if __name__ == "__main__":
    print("Testing Agentic Framework...")

    print("\n=== Test 1: Direct Answer ===")
    test_direct_answer()

    print("\n=== Test 2: SQL Agent ===")
    test_sql_agent()

    print("\n=== Test 3: Graph Agent ===")
    test_graph_agent()

    print("\nAll tests completed!")