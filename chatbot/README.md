# Chatbot Service

This is the **conversational API** for the Account Q&A Bot. Python package using **Semantic Kernel (Python)**.

## Responsibilities
- Expose HTTP endpoints (e.g., `/ask`, `/health`) for the SPA via APIM
- Manage conversation **history**, **planning**, **RBAC**, and **tool calls**
- Branch into **SQL**, **Graph**, or **Hybrid** strategies
- Use **Account Resolver** (LLM extract + cosine similarity) before SQL/Graph
- Generate final grounded answers with citations
