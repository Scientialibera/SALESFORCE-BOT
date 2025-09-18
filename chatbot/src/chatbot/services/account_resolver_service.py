"""Account Resolver (description only).

- LLM extracts candidate account name from user query.
- Fetch allowed accounts (via SQL schema repo or cache).
- Compute embeddings + cosine similarity; return canonical account_id/name.
- Confidence threshold -> ask user to disambiguate.
"""
