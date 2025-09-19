#!/usr/bin/env python3
"""Test Cosmos DB client method."""

from azure.cosmos.aio import CosmosClient
from azure.identity import DefaultAzureCredential

# Test the Cosmos DB client method names
client = CosmosClient("https://dummy.documents.azure.com:443/", DefaultAzureCredential())

# Check available methods
methods = [method for method in dir(client) if 'database' in method.lower()]
print("Available database-related methods:")
for method in methods:
    print(f"  - {method}")

# Check the correct method
print(f"\nHas get_database_client: {hasattr(client, 'get_database_client')}")
print(f"Has get_database: {hasattr(client, 'get_database')}")
print(f"Has database: {hasattr(client, 'database')}")