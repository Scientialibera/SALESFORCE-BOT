# Create a .env file with sensible defaults for local development
# This script overwrites .env in the repo root. Run from project root.

$envContent = @'
# Development .env for Account Q&A Bot
DEV_MODE=true
# Azure OpenAI
AOAI_ENDPOINT=https://salesforcebot-aoai.cognitiveservices.azure.com
AOAI_CHAT_DEPLOYMENT=chat-deployment
AOAI_EMBEDDING_DEPLOYMENT=embedding-deployment

# Cosmos DB
COSMOS_ENDPOINT=https://salesforcebot-cosmos-sql.documents.azure.com:443/
COSMOS_DATABASE_NAME=appdb
COSMOS_CHAT_CONTAINER=chat_history
COSMOS_CACHE_CONTAINER=cache
COSMOS_FEEDBACK_CONTAINER=feedback
COSMOS_AGENT_FUNCTIONS_CONTAINER=agent_functions
COSMOS_PROMPTS_CONTAINER=prompts
COSMOS_SQL_SCHEMA_CONTAINER=sql_schema
COSMOS_CONTRACTS_TEXT_CONTAINER=contracts_text
COSMOS_PROCESSED_FILES_CONTAINER=processed_files
COSMOS_ACCOUNT_RESOLVER_CONTAINER=account_resolver

# Gremlin (Graph)
GREMLIN_ENDPOINT=https://salesforcebot-cosmos-graph.gremlin.cosmos.azure.com:443/
GREMLIN_DATABASE_NAME=graphdb
GREMLIN_GRAPH_NAME=account_graph

# Fabric (kept present but may not be used in dev)
FABRIC_SQL_ENDPOINT=https://my-fabric.sql
FABRIC_DATABASE=lakehouse_db
FABRIC_WORKSPACE_ID=

# RBAC
RBAC_ENFORCE_RBAC=false
RBAC_ADMIN_USERS=

# Telemetry
TELEMETRY_ENABLE_TELEMETRY=false

# Security
SECURITY_JWT_SECRET_KEY=dev-secret

# Developer placeholders (will be written by server if a token is found)
DEV_USER_EMAIL=
DEV_USER_OID=
'@

$envPath = Join-Path -Path (Get-Location) -ChildPath ".env"
Write-Output "Writing .env to $envPath"
Set-Content -Path $envPath -Value $envContent -Encoding UTF8
Write-Output "Done. You can now run .\scripts\start_server.ps1 to start the app."
