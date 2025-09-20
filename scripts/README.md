Scripts for local development and deploying artifacts to Cosmos DB.

Files:
- set_env.ps1: Writes a .env file with sensible defaults for development.
- start_server.ps1: Starts the FastAPI app with uvicorn and writes logs to server.log.
- upload_artifacts.py: Python script that uploads prompts and function definitions from scripts/assets to Cosmos DB. It deletes existing items before reuploading.

Usage:
1. From project root, create the .env:
   Powershell: .\scripts\set_env.ps1
2. Start the server:
   Powershell: .\scripts\start_server.ps1
3. Upload prompts and functions:
   python .\scripts\upload_artifacts.py

Notes:
- The upload script expects the app settings in .env and will attempt to create a Cosmos DB client using the configured endpoint and credentials.
- The scripts consolidate previously scattered files under scripts/assets for easier management.
 
Centralization:
- All prompts and agent/function JSON definitions should live in `scripts/assets/prompts` and `scripts/assets/functions` respectively.
- `upload_artifacts.py` reads only from `scripts/assets/*` and will upload everything to Cosmos; chatbot/functions has been removed to avoid duplicates.

Functions layout:
- `scripts/assets/functions/agents` - agent manifests (registrations) describing agent capabilities that the planner uses to route requests.
- `scripts/assets/functions/tools` - tool/function definitions (the actual callable tools the agents use, e.g. SQL execution, graph traversal).

The upload script will:
1. Upload system prompts from `scripts/assets/prompts`.
2. Upload tool definitions from `scripts/assets/functions/tools` (reads JSON arrays under the `functions` key).
3. Upload agent registrations from `scripts/assets/functions/agents` (these are converted into function-like entries so the planner can discover agents and their metadata).

This keeps a clear separation between agent manifests and callable tools.

Loading at runtime:
- The app loads prompts and function definitions from Cosmos at startup. Use `upload_artifacts.py` to ensure Cosmos contains the latest artifacts before starting the app in dev or test environments.
