"""Cosmos DB NoSQL client for document storage."""

import asyncio
import logging
from typing import Dict, List, Optional, Any, AsyncGenerator
from azure.identity.aio import DefaultAzureCredential
from azure.cosmos.aio import CosmosClient as AzureCosmosClient
from azure.cosmos import PartitionKey, exceptions
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from ..config.settings import Settings


logger = logging.getLogger(__name__)


class CosmosClient:
    """Client for Azure Cosmos DB NoSQL API."""
    
    def __init__(self, settings: Settings):
        """Initialize the Cosmos client."""
        self.settings = settings
        self.credential = DefaultAzureCredential()
        self.client: Optional[AzureCosmosClient] = None
        self.database = None
        self._initialized = False
    
    async def initialize(self):
        """Initialize the async client."""
        if self._initialized:
            return
        
        try:
            self.client = AzureCosmosClient(
                url=self.settings.cosmos.endpoint,
                credential=self.credential
            )
            
            # Get or create database
            self.database = self.client.get_database_client(self.settings.cosmos.database_name)
            
            self._initialized = True
            logger.info("Cosmos DB client initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize Cosmos DB client: {e}")
            raise
    
    async def close(self):
        """Close the client and clean up resources."""
        if self.client:
            await self.client.close()
        if self.credential:
            await self.credential.close()
        self._initialized = False
    
    async def __aenter__(self):
        """Async context manager entry."""
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.close()
    
    async def _get_container(self, container_name: str, partition_key: str = "/id"):
        """Get or create a container."""
        try:
            return self.database.get_container_client(container_name)
        except exceptions.CosmosResourceNotFoundError:
            # Container doesn't exist, create it
            logger.info(f"Creating container {container_name}")
            return await self.database.create_container(
                id=container_name,
                partition_key=PartitionKey(path=partition_key),
                offer_throughput=400  # Start with minimal throughput
            )
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((exceptions.CosmosHttpResponseError,))
    )
    async def create_document(self, container_name: str, document: Dict[str, Any], 
                             partition_key: str = "/id") -> Dict[str, Any]:
        """Create a document in the specified container."""
        if not self._initialized:
            await self.initialize()
        
        try:
            container = await self._get_container(container_name, partition_key)
            
            result = await container.create_item(body=document)
            logger.debug(f"Created document {document.get('id')} in {container_name}")
            
            return result
            
        except exceptions.CosmosResourceExistsError:
            logger.warning(f"Document {document.get('id')} already exists in {container_name}")
            return await self.update_document(container_name, document, partition_key)
        except Exception as e:
            logger.error(f"Failed to create document in {container_name}: {e}")
            raise
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((exceptions.CosmosHttpResponseError,))
    )
    async def read_document(self, container_name: str, document_id: str, 
                           partition_key_value: str = None) -> Optional[Dict[str, Any]]:
        """Read a document by ID."""
        if not self._initialized:
            await self.initialize()
        
        try:
            container = await self._get_container(container_name)
            
            partition_key_value = partition_key_value or document_id
            
            result = await container.read_item(
                item=document_id,
                partition_key=partition_key_value
            )
            
            return result
            
        except exceptions.CosmosResourceNotFoundError:
            logger.debug(f"Document {document_id} not found in {container_name}")
            return None
        except Exception as e:
            logger.error(f"Failed to read document {document_id} from {container_name}: {e}")
            raise
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((exceptions.CosmosHttpResponseError,))
    )
    async def update_document(self, container_name: str, document: Dict[str, Any],
                             partition_key: str = "/id") -> Dict[str, Any]:
        """Update an existing document."""
        if not self._initialized:
            await self.initialize()
        
        try:
            container = await self._get_container(container_name, partition_key)
            
            result = await container.upsert_item(body=document)
            logger.debug(f"Updated document {document.get('id')} in {container_name}")
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to update document in {container_name}: {e}")
            raise
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type((exceptions.CosmosHttpResponseError,))
    )
    async def delete_document(self, container_name: str, document_id: str,
                             partition_key_value: str = None) -> bool:
        """Delete a document by ID."""
        if not self._initialized:
            await self.initialize()
        
        try:
            container = await self._get_container(container_name)
            
            partition_key_value = partition_key_value or document_id
            
            await container.delete_item(
                item=document_id,
                partition_key=partition_key_value
            )
            
            logger.debug(f"Deleted document {document_id} from {container_name}")
            return True
            
        except exceptions.CosmosResourceNotFoundError:
            logger.debug(f"Document {document_id} not found in {container_name}")
            return False
        except Exception as e:
            logger.error(f"Failed to delete document {document_id} from {container_name}: {e}")
            raise
    
    async def query_documents(self, container_name: str, query: str, 
                             parameters: List[Dict[str, Any]] = None,
                             partition_key: str = "/id",
                             max_items: int = None) -> AsyncGenerator[Dict[str, Any], None]:
        """Query documents using SQL."""
        if not self._initialized:
            await self.initialize()
        
        try:
            container = await self._get_container(container_name, partition_key)
            
            query_iterable = container.query_items(
                query=query,
                parameters=parameters or [],
                enable_cross_partition_query=True,
                max_item_count=max_items
            )
            
            item_count = 0
            async for item in query_iterable:
                yield item
                item_count += 1
                if max_items and item_count >= max_items:
                    break
                    
        except Exception as e:
            logger.error(f"Failed to query documents in {container_name}: {e}")
            raise
    
    async def query_documents_list(self, container_name: str, query: str,
                                  parameters: List[Dict[str, Any]] = None,
                                  partition_key: str = "/id",
                                  max_items: int = None) -> List[Dict[str, Any]]:
        """Query documents and return as a list."""
        results = []
        async for item in self.query_documents(container_name, query, parameters, partition_key, max_items):
            results.append(item)
        return results
    
    async def batch_create_documents(self, container_name: str, documents: List[Dict[str, Any]],
                                   partition_key: str = "/id") -> List[Dict[str, Any]]:
        """Create multiple documents in batches."""
        if not self._initialized:
            await self.initialize()
        
        if not documents:
            return []
        
        try:
            container = await self._get_container(container_name, partition_key)
            
            # Process in batches of 100 (Cosmos DB limit)
            batch_size = 100
            results = []
            
            for i in range(0, len(documents), batch_size):
                batch = documents[i:i + batch_size]
                
                # Group by partition key for batch operations
                partition_groups = {}
                for doc in batch:
                    pk_value = doc.get(partition_key.replace("/", ""), doc.get("id"))
                    if pk_value not in partition_groups:
                        partition_groups[pk_value] = []
                    partition_groups[pk_value].append(doc)
                
                # Process each partition group
                for pk_value, group_docs in partition_groups.items():
                    tasks = []
                    for doc in group_docs:
                        tasks.append(container.upsert_item(body=doc))
                    
                    batch_results = await asyncio.gather(*tasks, return_exceptions=True)
                    
                    for result in batch_results:
                        if isinstance(result, Exception):
                            logger.error(f"Failed to create document in batch: {result}")
                        else:
                            results.append(result)
                
                # Brief pause between batches
                if i + batch_size < len(documents):
                    await asyncio.sleep(0.1)
            
            logger.info(f"Batch created {len(results)} documents in {container_name}")
            return results
            
        except Exception as e:
            logger.error(f"Failed to batch create documents in {container_name}: {e}")
            raise
    
    async def get_document_count(self, container_name: str, partition_key: str = "/id") -> int:
        """Get the total number of documents in a container."""
        try:
            query = "SELECT VALUE COUNT(1) FROM c"
            results = await self.query_documents_list(container_name, query, partition_key=partition_key, max_items=1)
            return results[0] if results else 0
            
        except Exception as e:
            logger.error(f"Failed to get document count for {container_name}: {e}")
            return 0
    
    async def search_documents(self, container_name: str, search_term: str, 
                              fields: List[str] = None, partition_key: str = "/id",
                              max_items: int = 100) -> List[Dict[str, Any]]:
        """Search documents by text content."""
        if not fields:
            fields = ["content", "title", "name"]
        
        # Build search query with CONTAINS for each field
        conditions = []
        parameters = []
        
        for i, field in enumerate(fields):
            param_name = f"@search{i}"
            conditions.append(f"CONTAINS(LOWER(c.{field}), {param_name})")
            parameters.append({"name": param_name, "value": search_term.lower()})
        
        query = f"SELECT * FROM c WHERE {' OR '.join(conditions)}"
        
        return await self.query_documents_list(
            container_name, query, parameters, partition_key, max_items
        )
    
    async def get_documents_by_date_range(self, container_name: str, 
                                         start_date: str, end_date: str,
                                         date_field: str = "created_at",
                                         partition_key: str = "/id") -> List[Dict[str, Any]]:
        """Get documents within a date range."""
        query = f"SELECT * FROM c WHERE c.{date_field} >= @start_date AND c.{date_field} <= @end_date"
        parameters = [
            {"name": "@start_date", "value": start_date},
            {"name": "@end_date", "value": end_date}
        ]
        
        return await self.query_documents_list(container_name, query, parameters, partition_key)
    
    async def test_connection(self) -> bool:
        """Test the connection to Cosmos DB."""
        try:
            await self.initialize()
            
            # Try to get database info
            database_info = await self.database.read()
            return database_info is not None
            
        except Exception as e:
            logger.error(f"Cosmos DB connection test failed: {e}")
            return False
    
    async def get_container_info(self, container_name: str) -> Dict[str, Any]:
        """Get information about a container."""
        try:
            container = await self._get_container(container_name)
            
            container_info = await container.read()
            
            return {
                "id": container_info.get("id"),
                "partition_key": container_info.get("partitionKey"),
                "indexing_policy": container_info.get("indexingPolicy"),
                "document_count": await self.get_document_count(container_name)
            }
            
        except Exception as e:
            logger.error(f"Failed to get container info for {container_name}: {e}")
            return {}
