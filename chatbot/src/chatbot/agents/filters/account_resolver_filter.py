"""Account Resolver filter (description only).

- Auto-runs before SQL/Graph agent calls.
- Extracts account name string and resolves to canonical account_id/name via cosine sim.
"""
