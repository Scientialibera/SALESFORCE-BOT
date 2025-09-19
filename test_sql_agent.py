#!/usr/bin/env python3
"""Test script for SQL agent functionality"""

import requests
import json

def test_sql_agent_queries():
    """Test queries that should route to SQL agent"""
    
    base_url = "http://localhost:8004"
    
    test_queries = [
        "Show me sales revenue for this quarter",
        "What are the top opportunities?",
        "How is our sales performance this month?",
        "Show me revenue data",
        "What are our biggest deals?",
        "Performance metrics for the sales team",
        "SQL query for opportunity data"
    ]
    
    for i, query in enumerate(test_queries, 1):
        print(f"\n{'='*60}")
        print(f"SQL Test {i}: {query}")
        print('='*60)
        
        payload = {
            "messages": [
                {
                    "role": "user",
                    "content": query
                }
            ],
            "user_id": "test_user",
            "session_id": f"sql_test_session_{i}"
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
                
                if 'choices' in data and len(data['choices']) > 0:
                    choice = data['choices'][0]
                    message = choice.get('message', {})
                    content = message.get('content', 'No content')
                    print(f"Response: {content}")
                
                if 'metadata' in data:
                    metadata = data['metadata']
                    print(f"Mode: {metadata.get('mode')}")
                    print(f"Plan Type: {metadata.get('plan_type')}")
                    if 'error' in metadata:
                        print(f"Error: {metadata['error']}")
                    print(f"Steps Executed: {metadata.get('steps_executed', 0)}")
                    print(f"Execution Status: {metadata.get('execution_status')}")
                
                print(f"Usage: {data.get('usage', {})}")
                
            else:
                print(f"Error response: {response.text}")
                
        except Exception as e:
            print(f"Request failed: {e}")
        
        print()

if __name__ == "__main__":
    print("Testing SQL Agent Functionality")
    test_sql_agent_queries()