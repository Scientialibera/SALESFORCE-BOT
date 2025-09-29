#!/usr/bin/env python3
"""
Test SQL agent functionality.
"""

import requests
import json

def test_sql_agent():
    url = "http://localhost:8000/api/v1/chat"
    headers = {"Content-Type": "application/json"}
    data = {
        "messages": [
            {"role": "user", "content": "All sales for MSFT"}
        ],
        "user_id": "test-user",
        "session_id": "test-session-sql"
    }

    try:
        print("Making SQL agent request...")
        response = requests.post(url, headers=headers, json=data, timeout=60)
        print(f"Status code: {response.status_code}")

        # Parse and pretty-print the response
        response_data = response.json()
        print("Response:")
        print(json.dumps(response_data, indent=2))

        # Check if it used agents
        metadata = response_data.get("metadata", {})
        planning_result = metadata.get("planning_result", {})
        total_agent_calls = planning_result.get("execution_metadata", {}).get("total_agent_calls", 0)

        print(f"\nAgent calls made: {total_agent_calls}")
        print(f"Plan type: {response_data.get('plan_type', 'unknown')}")

    except Exception as e:
        print(f"Request failed: {e}")

if __name__ == "__main__":
    test_sql_agent()