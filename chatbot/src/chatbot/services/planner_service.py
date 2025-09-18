"""Planner / Orchestrator (description only).

- Single chat-facing LLM (Semantic Kernel).
- Decides whether to call SQL Agent, Graph Agent, both, or answer directly.
- Merges tool results and formats final answer with citations.
- Enforces high-level safety and RBAC guardrails.
"""
