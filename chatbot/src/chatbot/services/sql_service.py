"""SQL service (description only).

- Generate/validate parameterized T-SQL from the SQL Agent.
- Inject RBAC filters (e.g., WHERE account_id IN ... AND owner_email = ...).
- Execute against Fabric SQL endpoint/Warehouse; return rows.
"""
