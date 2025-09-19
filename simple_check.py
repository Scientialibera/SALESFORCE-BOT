#!/usr/bin/env python3
"""Simple script to check agent functions in Cosmos DB using Python REPL approach"""

import sys
import os
sys.path.append('chatbot/src')

# Quick check of what's in the functions container
print("Checking if agent functions container has any data...")

# First let's check if we can connect to Cosmos DB at all
from dotenv import load_dotenv
load_dotenv()

print("Environment variables loaded")
print(f"COSMOS_ENDPOINT: {os.getenv('COSMOS_ENDPOINT')}")
print(f"COSMOS_DATABASE_NAME: {os.getenv('COSMOS_DATABASE_NAME')}")
print(f"COSMOS_AGENT_FUNCTIONS_CONTAINER: {os.getenv('COSMOS_AGENT_FUNCTIONS_CONTAINER')}")

# Quick test of Azure Cosmos DB connection
try:
    from azure.cosmos.aio import CosmosClient
    from azure.identity.aio import DefaultAzureCredential
    
    print("Azure imports successful")
    
    # Use sync client for simplicity
    from azure.cosmos import CosmosClient as SyncCosmosClient
    from azure.identity import DefaultAzureCredential as SyncDefaultAzureCredential
    
    endpoint = os.getenv('COSMOS_ENDPOINT')
    credential = SyncDefaultAzureCredential()
    client = SyncCosmosClient(endpoint, credential)
    
    database_name = os.getenv('COSMOS_DATABASE_NAME')
    container_name = os.getenv('COSMOS_AGENT_FUNCTIONS_CONTAINER', 'agent_functions')
    
    print(f"Attempting to connect to database: {database_name}")
    print(f"Container: {container_name}")
    
    database = client.get_database_client(database_name)
    container = database.get_container_client(container_name)
    
    # Simple query to count items
    query = "SELECT VALUE COUNT(1) FROM c"
    items = list(container.query_items(query=query))
    count = items[0] if items else 0
    
    print(f"Total items in {container_name} container: {count}")
    
    if count > 0:
        # Get first few items
        query = "SELECT * FROM c"
        items = list(container.query_items(query=query))
        
        print(f"First {min(5, len(items))} items:")
        for i, item in enumerate(items[:5]):
            print(f"  {i+1}. {item.get('name', 'No name')} - {item.get('description', 'No description')[:50]}...")
    else:
        print("No agent functions found in Cosmos DB!")
        print("This means we need to upload the function definitions.")
        
except Exception as e:
    print(f"Error connecting to Cosmos DB: {e}")
    import traceback
    traceback.print_exc()