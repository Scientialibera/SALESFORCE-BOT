"""Test script to verify conversation history retrieval with full metadata."""

import requests
import json

API_URL = "http://localhost:8000/api/v1/chat"

def test_history_retrieval():
    """Test retrieving conversation history with empty messages array."""

    # Request payload with session_id but no messages
    payload = {
        "messages": [],
        "user_id": "user@example.com",
        "session_id": "test-session-sql",  # Use existing session from previous test
        "metadata": {}
    }

    print("Requesting conversation history...")
    print(f"Session ID: {payload['session_id']}")
    print()

    try:
        response = requests.post(API_URL, json=payload)
        print(f"Status code: {response.status_code}")

        if response.status_code == 200:
            data = response.json()

            # Check if history metadata is present
            if data.get("metadata", {}).get("history"):
                print("\n✓ History retrieved successfully!")
                print(f"Total turns: {data['metadata'].get('total_turns', 0)}")

                # Display each turn with metadata
                turns = data["metadata"].get("turns", [])
                for i, turn in enumerate(turns):
                    print(f"\n--- Turn {i + 1} ---")
                    print(f"Turn ID: {turn.get('turn_id')}")
                    print(f"Turn Number: {turn.get('turn_number')}")

                    # User message
                    user_msg = turn.get("user_message", {})
                    print(f"\nUser: {user_msg.get('content', '')[:100]}...")

                    # Assistant message
                    assistant_msg = turn.get("assistant_message", {})
                    if assistant_msg:
                        print(f"\nAssistant: {assistant_msg.get('content', '')[:100]}...")

                    # Timing
                    print(f"\nTiming:")
                    print(f"  Planning: {turn.get('planning_time_ms')} ms")
                    print(f"  Total: {turn.get('total_time_ms')} ms")

                    # Execution metadata (lineage)
                    exec_meta = turn.get("execution_metadata", {})
                    if exec_meta:
                        print(f"\nExecution Lineage:")
                        print(f"  Total Agent Calls: {exec_meta.get('total_agent_calls', 0)}")
                        print(f"  Total Rounds: {exec_meta.get('final_round', 0)}")

                        rounds = exec_meta.get("rounds", [])
                        if rounds:
                            print(f"  Rounds Detail:")
                            for round_data in rounds:
                                round_num = round_data.get("round", 0)
                                agent_execs = round_data.get("agent_executions", [])
                                print(f"    Round {round_num}: {len(agent_execs)} agent execution(s)")
                                for agent_exec in agent_execs:
                                    agent_name = agent_exec.get("agent_name", "unknown")
                                    tool_calls = agent_exec.get("tool_calls", [])
                                    print(f"      - {agent_name}: {len(tool_calls)} tool call(s)")

                print("\n" + "="*80)
                print("Full JSON response (first 500 chars):")
                print(json.dumps(data, indent=2)[:500] + "...")

            else:
                print("Warning: Response doesn't indicate history retrieval")
                print(json.dumps(data, indent=2))
        else:
            print(f"Error: {response.status_code}")
            print(response.text)

    except Exception as e:
        print(f"Error making request: {e}")


if __name__ == "__main__":
    test_history_retrieval()