"""HTTP route: /ask (description only).

- Accepts: chat_id, user text, optional client metadata.
- Looks up history, sends to Planner, returns grounded answer + citations.
- Records feedback endpoints (e.g., /feedback).
"""
