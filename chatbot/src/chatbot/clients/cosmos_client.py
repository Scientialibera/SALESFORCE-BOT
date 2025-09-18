"""
Azure Cosmos DB client with Managed Identity authentication.

This module provides a client for Cosmos DB NoSQL operations using DefaultAzureCredential
for authentication and proper error handling with retry logic.
"""

import asyncio
import logging
from typing import Optional, Dict, Any, List, Union
from azure.identity import DefaultAzureCredential
from azure.cosmos.aio import CosmosClient as AsyncCosmosClient
from azure.cosmos import PartitionKey, exceptions
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)
import structlog

from chatbot.config.settings import CosmosDBSettings

logger = structlog.get_logger(__name__)


class CosmosDBClient:
    """
    Azure Cosmos DB client with Managed Identity authentication and retry logic.
    
    This client handles:
    - Token-based authentication using DefaultAzureCredential
    - Automatic container creation if needed
    - Retry logic for transient failures
    - Proper error handling and logging
    """
    
    def __init__(self, settings: CosmosDBSettings):
        """
        Initialize the Cosmos DB client.
        
        Args:
            settings: Cosmos DB configuration settings
        """
        self.settings = settings
        self._credential = DefaultAzureCredential()
        self._client: Optional[AsyncCosmosClient] = None
        self._database = None
        self._containers: Dict[str, Any] = {}
        
        logger.info(
            "Initializing Cosmos DB client",
            endpoint=settings.endpoint,
            database=settings.database_name,
        )
    
    async def _get_client(self) -> AsyncCosmosClient:
        """Get or create Cosmos DB client."""
        if self._client is None:
            self._client = AsyncCosmosClient(
                url=self.settings.endpoint,
                credential=self._credential,
            )
            logger.info("Created Cosmos DB client with managed identity")
        
        return self._client
    
    async def _get_database(self):
        """Get or create database."""
        if self._database is None:
            client = await self._get_client()
            self._database = client.get_database_client(self.settings.database_name)
            logger.debug("Connected to database", database=self.settings.database_name)
        
        return self._database
    
    async def _get_container(self, container_name: str, partition_key: str = "/id"):
        """Get or create container."""
        if container_name not in self._containers:
            database = await self._get_database()
            
            try:
                # Try to get existing container
                container = database.get_container_client(container_name)
                await container.read()  # Test if container exists
                self._containers[container_name] = container
                logger.debug("Connected to existing container", container=container_name)
                
            except exceptions.CosmosResourceNotFoundError:
                # Create container if it doesn't exist
                container = await database.create_container(
                    id=container_name,
                    partition_key=PartitionKey(path=partition_key),
                    offer_throughput=400,  # Minimum RU/s
                )
                self._containers[container_name] = container
                logger.info("Created new container", container=container_name)
        
        return self._containers[container_name]
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((exceptions.CosmosHttpResponseError,)),
    )
    async def create_item(
        self,
        container_name: str,
        item: Dict[str, Any],
        partition_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create an item in the specified container.
        
        Args:
            container_name: Name of the container
            item: Item data to create
            partition_key: Optional partition key path
            
        Returns:
            Created item with metadata
        """
        container = await self._get_container(container_name, partition_key or "/id")
        
        try:
            result = await container.create_item(body=item)
            logger.debug(
                "Item created",
                container=container_name,
                item_id=item.get("id"),
                ru_charge=result.get("_charge", 0),
            )
            return result
            
        except Exception as e:
            logger.error(
                "Failed to create item",
                container=container_name,
                item_id=item.get("id"),
                error=str(e),
            )
            raise
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((exceptions.CosmosHttpResponseError,)),
    )
    async def read_item(
        self,
        container_name: str,
        item_id: str,
        partition_key_value: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Read an item from the specified container.
        
        Args:
            container_name: Name of the container
            item_id: ID of the item to read
            partition_key_value: Value of the partition key
            
        Returns:
            Item data or None if not found
        """
        container = await self._get_container(container_name)
        
        try:
            result = await container.read_item(
                item=item_id,
                partition_key=partition_key_value,
            )
            logger.debug(
                "Item read",
                container=container_name,
                item_id=item_id,
                ru_charge=result.get("_charge", 0),
            )
            return result
            
        except exceptions.CosmosResourceNotFoundError:
            logger.debug("Item not found", container=container_name, item_id=item_id)
            return None
        except Exception as e:
            logger.error(
                "Failed to read item",
                container=container_name,
                item_id=item_id,
                error=str(e),
            )
            raise
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((exceptions.CosmosHttpResponseError,)),
    )
    async def upsert_item(
        self,
        container_name: str,
        item: Dict[str, Any],
        partition_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Upsert an item in the specified container.
        
        Args:
            container_name: Name of the container
            item: Item data to upsert
            partition_key: Optional partition key path
            
        Returns:
            Upserted item with metadata
        """
        container = await self._get_container(container_name, partition_key or "/id")
        
        try:
            result = await container.upsert_item(body=item)
            logger.debug(
                "Item upserted",
                container=container_name,
                item_id=item.get("id"),
                ru_charge=result.get("_charge", 0),
            )
            return result
            
        except Exception as e:
            logger.error(
                "Failed to upsert item",
                container=container_name,
                item_id=item.get("id"),
                error=str(e),
            )
            raise
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((exceptions.CosmosHttpResponseError,)),
    )
    async def delete_item(
        self,
        container_name: str,
        item_id: str,
        partition_key_value: str,
    ) -> bool:
        """
        Delete an item from the specified container.
        
        Args:
            container_name: Name of the container
            item_id: ID of the item to delete
            partition_key_value: Value of the partition key
            
        Returns:
            True if deleted, False if not found
        """
        container = await self._get_container(container_name)
        
        try:
            await container.delete_item(
                item=item_id,
                partition_key=partition_key_value,
            )
            logger.debug("Item deleted", container=container_name, item_id=item_id)
            return True
            
        except exceptions.CosmosResourceNotFoundError:
            logger.debug("Item not found for deletion", container=container_name, item_id=item_id)
            return False
        except Exception as e:
            logger.error(
                "Failed to delete item",
                container=container_name,
                item_id=item_id,
                error=str(e),
            )
            raise
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((exceptions.CosmosHttpResponseError,)),
    )
    async def query_items(
        self,
        container_name: str,
        query: str,
        parameters: Optional[List[Dict[str, Any]]] = None,
        partition_key_value: Optional[str] = None,
        max_item_count: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Query items from the specified container.
        
        Args:
            container_name: Name of the container
            query: SQL query string
            parameters: Optional query parameters
            partition_key_value: Optional partition key for cross-partition query
            max_item_count: Optional maximum number of items to return
            
        Returns:
            List of matching items
        """
        container = await self._get_container(container_name)
        
        try:
            query_options = {}
            if partition_key_value:
                query_options["partition_key"] = partition_key_value
            if max_item_count:
                query_options["max_item_count"] = max_item_count
            
            items = []
            async for item in container.query_items(
                query=query,
                parameters=parameters or [],
                **query_options
            ):
                items.append(item)
            
            logger.debug(
                "Items queried",
                container=container_name,
                query=query,
                result_count=len(items),
            )
            return items
            
        except Exception as e:
            logger.error(
                "Failed to query items",
                container=container_name,
                query=query,
                error=str(e),
            )
            raise
    
    async def close(self):
        """Close the client and clean up resources."""
        if self._client:
            await self._client.close()
            self._client = None
            self._database = None
            self._containers.clear()
        
        logger.info("Cosmos DB client closed")
