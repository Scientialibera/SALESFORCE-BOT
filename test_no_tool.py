#!/usr/bin/env python3
"""Test script for no-tool responses"""

import requests
import json

def test_no_tool_queries():
    """Test queries that should use no tools and return direct answers"""
    
    base_url = "http://localhost:8004"
    
    test_queries = [
        "Hello, how are you?",
        "What is the weather like today?", 
        "Can you explain what artificial intelligence is?",
        "Tell me a joke",
        "What time is it?",
        "How do I make coffee?"
    ]
    
    for i, query in enumerate(test_queries, 1):
        print(f"\n{'='*60}")
        print(f"Test {i}: {query}")
        print('='*60)
        
        payload = {
            "messages": [
                {
                    "role": "user",
                    "content": query
                }
            ],
            "user_id": "test_user",
            "session_id": f"test_session_{i}"
        }
        
        try:
            response = requests.post(
                f"{base_url}/api/chat",
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            
            print(f"Status: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                print(f"Session ID: {data.get('session_id')}")
                print(f"Turn ID: {data.get('turn_id')}")
                
                if 'choices' in data and len(data['choices']) > 0:
                    choice = data['choices'][0]
                    message = choice.get('message', {})
                    content = message.get('content', 'No content')
                    print(f"Response: {content}")
                    print(f"Finish Reason: {choice.get('finish_reason')}")
                
                if 'metadata' in data:
                    metadata = data['metadata']
                    print(f"Mode: {metadata.get('mode')}")
                    if 'error' in metadata:
                        print(f"Error: {metadata['error']}")
                    print(f"Plan ID: {metadata.get('plan_id', 'None')}")
                
                print(f"Usage: {data.get('usage', {})}")
                
            else:
                print(f"Error response: {response.text}")
                
        except Exception as e:
            print(f"Request failed: {e}")
        
        print()

if __name__ == "__main__":
    print("Testing No-Tool Functionality")
    test_no_tool_queries()