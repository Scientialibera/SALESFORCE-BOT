# Indexer Service

Background worker that ingests/refreshes searchable signals for the chatbot.

## Responsibilities
- Discover new/changed SharePoint PDFs (via inventory/ETag/LastModified)
- Extract text (Azure AI Document Intelligence), chunk, and store in vector store
- Sync structured schema hints (for SQL Agent) into `sql_schema`
- Track progress (`processed_files`) and emit telemetry
