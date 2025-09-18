"""Application wiring (description only).

- Build FastAPI app instance.
- Add routes from `routes/`.
- Initialize Semantic Kernel (Python) with AOAI (token auth).
- Register agents (SQL, Graph, Hybrid) and filters (RBAC, Account Resolver).
- Configure telemetry (App Insights), CORS (if needed behind APIM), health checks.
"""
