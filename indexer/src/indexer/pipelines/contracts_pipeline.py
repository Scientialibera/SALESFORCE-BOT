"""Pipeline: Contracts (description only).

Steps:
1) Enumerate SharePoint file inventory (account folder mapping).
2) Anti-join against `processed_files` (by ETag/LastModified).
3) For each new/changed PDF: fetch → extract text (Doc Intelligence) → chunk.
4) Write chunks + metadata to vector store; update `processed_files`.
"""
