"""RBAC service (description only).

- Build rbacContext from JWT (user id/email/roles/tenant).
- Provide allowlists for accounts/projects to downstream agents.
- Inject WHERE predicates / Gremlin predicates as needed.
"""
