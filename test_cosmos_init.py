#!/usr/bin/env python3
"""Test Cosmos DB client initialization."""

import asyncio
import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'chatbot', 'src'))

from chatbot.config.settings import settings
from chatbot.clients.cosmos_client import CosmosDBClient

async def test_cosmos_client():
    """Test the Cosmos DB client initialization."""
    try:
        print("Testing Cosmos DB client...")
        
        # Create client
        client = CosmosDBClient(settings.cosmos_db)
        print(f"✅ Client created")
        
        # Test getting async client
        async_client = await client._get_client()
        print(f"✅ Async client obtained: {type(async_client)}")
        
        # Check methods
        print(f"Has get_database_client: {hasattr(async_client, 'get_database_client')}")
        
        # Try getting database
        database = await client._get_database()
        print(f"✅ Database obtained: {type(database)}")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_cosmos_client())