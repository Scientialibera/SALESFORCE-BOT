"""
Simple test runner for the planner/agent scenarios.
Sends four scenario requests to the running FastAPI server and records responses.

Usage (from repo root):
  python -m pytest chatbot/tests/test_planner_scenarios.py -q

This test assumes the API is running at http://localhost:8000 and that
server.log is writable at the repo root. Adjust SERVER_URL if different.
"""
import json
import os
import time
import requests

SERVER_URL = os.environ.get("TEST_SERVER_URL", "http://localhost:8000")
CHAT_ENDPOINT = f"{SERVER_URL}/api/v1/chat"
RESULTS_PATH = os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, "scripts", "assets", "tools", "agent_test_responses.json")

SCENARIOS = [
    {"name": "no_tool", "payload": {"messages": [{"role": "user", "content": "Answer as best you can without calling tools."}], "planner_mode": "no_tool", "user_id": "tester_no_tool", "session_id": "s_no_tool"}},
    {"name": "sql_only", "payload": {"messages": [{"role": "user", "content": "Run a SQL-only plan to fetch account info."}], "planner_mode": "sql_only", "user_id": "tester_sql", "session_id": "s_sql"}},
    {"name": "graph_only", "payload": {"messages": [{"role": "user", "content": "Run a Graph-only plan to explore relationships."}], "planner_mode": "graph_only", "user_id": "tester_graph", "session_id": "s_graph"}},
    {"name": "hybrid", "payload": {"messages": [{"role": "user", "content": "Use any tools necessary to answer and combine SQL and Graph."}], "planner_mode": "hybrid", "user_id": "tester_hybrid", "session_id": "s_hybrid"}},
]


def tail_log(path, lines=200):
    if not os.path.exists(path):
        return ""
    with open(path, "rb") as f:
        try:
            f.seek(0, os.SEEK_END)
            end = f.tell()
            size = 1024 * 64
            seek = max(0, end - size)
            f.seek(seek)
            data = f.read().decode(errors="ignore")
            return data
        except OSError:
            return ""


def save_results(results):
    os.makedirs(os.path.dirname(RESULTS_PATH), exist_ok=True)
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)


def run_scenarios():
    results = {"runs": [], "timestamp": time.time()}

    for s in SCENARIOS:
        name = s["name"]
        payload = s["payload"]
        try:
            resp = requests.post(CHAT_ENDPOINT, json=payload, timeout=60)
            body = {
                "status_code": resp.status_code,
                "json": None,
                "text": None,
            }
            try:
                body["json"] = resp.json()
            except Exception:
                body["text"] = resp.text
        except Exception as e:
            body = {"error": str(e)}

        # capture recent server.log tail
        log_tail = tail_log(os.path.join(os.getcwd(), "server.log"), lines=200)

        results["runs"].append({"scenario": name, "response": body, "log_tail": log_tail})
        # brief pause between runs
        time.sleep(2)

    save_results(results)
    return results


if __name__ == "__main__":
    r = run_scenarios()
    print(json.dumps(r, indent=2)[:2000])
