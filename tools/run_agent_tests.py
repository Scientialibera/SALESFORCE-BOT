import json
import requests

URL = "http://127.0.0.1:8000/api/v1/chat"

scenarios = [
    {
        "name": "no_tool",
        "payload": {
            "session_id": "s_no_tool",
            "user_id": "tester_no_tool",
            "messages": [{"role": "user", "content": "Who is the current President of the United States?"}],
            "metadata": {}
        }
    },
    {
        "name": "sql_only",
        "payload": {
            "session_id": "s_sql",
            "user_id": "tester_sql",
            "messages": [{"role": "user", "content": "List opportunities for TechCorp Industries in Q3."}],
            "metadata": {}
        }
    },
    {
        "name": "graph_only",
        "payload": {
            "session_id": "s_graph",
            "user_id": "tester_graph",
            "messages": [{"role": "user", "content": "Show connections between TechCorp Industries and Retail Giant Corp."}],
            "metadata": {}
        }
    },
    {
        "name": "hybrid",
        "payload": {
            "session_id": "s_hybrid",
            "user_id": "tester_hybrid",
            "messages": [{"role": "user", "content": "Find the latest contract for TechCorp and its primary owner email, then summarize key clauses."}],
            "metadata": {}
        }
    }
]

results = {}
for s in scenarios:
    name = s["name"]
    print(f"Running scenario: {name}")
    try:
        # Use a conservative per-request timeout so slow backends don't block the whole run
        r = requests.post(URL, json=s["payload"], timeout=30)
        try:
            body = r.json()
        except Exception:
            body = r.text
        results[name] = {
            "status_code": r.status_code,
            "body": body
        }
        print(name, "->", r.status_code)
    except Exception as e:
        results[name] = {"error": str(e)}
        print(name, "ERROR", str(e))

with open("tools/agent_test_responses.json", "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2)

print("Saved results to tools/agent_test_responses.json")
