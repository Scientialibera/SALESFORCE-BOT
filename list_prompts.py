import asyncio
import sys
from pathlib import Path
import json

# Ensure chatbot/src is on path when running this script directly.
file_path = Path(__file__).resolve()
repo_root = file_path.parent
chatbot_src = repo_root / "chatbot" / "src"
sys.path.insert(0, str(chatbot_src))

from chatbot.config.settings import settings
from chatbot.clients.cosmos_client import CosmosDBClient
from chatbot.repositories.prompts_repository import PromptsRepository

async def main():
    cosmos_client = CosmosDBClient(settings.cosmos_db)
    prompts_repo = PromptsRepository(
        cosmos_client,
        settings.cosmos_db.database_name,
        settings.cosmos_db.prompts_container,
    )

    try:
        prompts = await prompts_repo.list_prompts()
        print(json.dumps(prompts, indent=2))
    finally:
        try:
            await cosmos_client.close()
        except Exception:
            pass

if __name__ == '__main__':
    asyncio.run(main())
