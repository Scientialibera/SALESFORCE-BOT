"""
Repository for caching operations using Azure Cosmos DB TTL.

This module provides caching functionality with automatic expiration
for embeddings, query results, and other frequently accessed data.
"""

import json
from typing import Any, Dict, Optional
from datetime import datetime, timedelta
import structlog

from azure.cosmos import exceptions as cosmos_exceptions
from azure.cosmos.aio import CosmosClient

logger = structlog.get_logger(__name__)


class CacheRepository:
    """Repository for caching operations with TTL support."""
    
    def __init__(self, cosmos_client: CosmosClient, database_name: str, container_name: str):
        """
        Initialize the cache repository.
        
        Args:
            cosmos_client: Azure Cosmos DB client
            database_name: Cosmos database name
            container_name: Container name for cache entries
        """
        self.cosmos_client = cosmos_client
        self.database_name = database_name
        self.container_name = container_name
        self._container = None
        
    async def _get_container(self):
        """Get or create the container reference."""
        if self._container is None:
            database = self.cosmos_client.get_database_client(self.database_name)
            self._container = database.get_container_client(self.container_name)
        return self._container
    
    async def get(self, key: str) -> Optional[Any]:
        """
        Get a cached value by key.
        
        Args:
            key: Cache key
            
        Returns:
            Cached value or None if not found/expired
        """
        try:
            container = await self._get_container()
            
            item = await container.read_item(
                item=key,
                partition_key=key
            )
            
            # Check if item has expired (additional safety check)
            if "expires_at" in item:
                expires_at = datetime.fromisoformat(item["expires_at"])
                if datetime.utcnow() > expires_at:
                    # Item has expired, delete it
                    await self.delete(key)
                    return None
            
            logger.debug("Cache hit", key=key)
            return item.get("value")
            
        except cosmos_exceptions.CosmosResourceNotFoundError:
            logger.debug("Cache miss", key=key)
            return None
        except Exception as e:
            logger.error(
                "Failed to get cache item",
                key=key,
                error=str(e)
            )
            # Return None on error to prevent cache failures from breaking app
            return None
    
    async def set(self, key: str, value: Any, ttl_seconds: int = 3600) -> bool:
        """
        Set a cached value with TTL.
        
        Args:
            key: Cache key
            value: Value to cache
            ttl_seconds: Time to live in seconds (default: 1 hour)
            
        Returns:
            True if set successfully
        """
        try:
            container = await self._get_container()
            
            expires_at = datetime.utcnow() + timedelta(seconds=ttl_seconds)
            
            cache_item = {
                "id": key,
                "value": value,
                "created_at": datetime.utcnow().isoformat(),
                "expires_at": expires_at.isoformat(),
                "ttl": ttl_seconds,  # Cosmos DB TTL field
            }
            
            await container.upsert_item(cache_item)
            
            logger.debug(
                "Cache set",
                key=key,
                ttl_seconds=ttl_seconds,
                expires_at=expires_at.isoformat()
            )
            
            return True
            
        except Exception as e:
            logger.error(
                "Failed to set cache item",
                key=key,
                error=str(e)
            )
            # Don't raise exception to prevent cache failures from breaking app
            return False
    
    async def delete(self, key: str) -> bool:
        """
        Delete a cached value.
        
        Args:
            key: Cache key to delete
            
        Returns:
            True if deleted successfully
        """
        try:
            container = await self._get_container()
            
            await container.delete_item(
                item=key,
                partition_key=key
            )
            
            logger.debug("Cache deleted", key=key)
            return True
            
        except cosmos_exceptions.CosmosResourceNotFoundError:
            logger.debug("Cache key not found for deletion", key=key)
            return False
        except Exception as e:
            logger.error(
                "Failed to delete cache item",
                key=key,
                error=str(e)
            )
            return False
    
    async def exists(self, key: str) -> bool:
        """
        Check if a cache key exists and is not expired.
        
        Args:
            key: Cache key to check
            
        Returns:
            True if key exists and is valid
        """
        value = await self.get(key)
        return value is not None
    
    async def clear_expired(self) -> int:
        """
        Manually clear expired cache entries.
        
        Note: Cosmos DB TTL should handle this automatically,
        but this method provides manual cleanup if needed.
        
        Returns:
            Number of expired entries cleared
        """
        try:
            container = await self._get_container()
            
            # Query for expired items
            now = datetime.utcnow().isoformat()
            query = "SELECT c.id FROM c WHERE c.expires_at < @now"
            parameters = [{"name": "@now", "value": now}]
            
            expired_keys = []
            async for item in container.query_items(
                query=query,
                parameters=parameters,
                enable_cross_partition_query=True
            ):
                expired_keys.append(item["id"])
            
            # Delete expired items
            deleted_count = 0
            for key in expired_keys:
                if await self.delete(key):
                    deleted_count += 1
            
            logger.info(
                "Cleared expired cache entries",
                expired_count=len(expired_keys),
                deleted_count=deleted_count
            )
            
            return deleted_count
            
        except Exception as e:
            logger.error("Failed to clear expired cache entries", error=str(e))
            return 0
    
    async def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.
        
        Returns:
            Dictionary with cache statistics
        """
        try:
            container = await self._get_container()
            
            # Count total items
            total_query = "SELECT VALUE COUNT(1) FROM c"
            total_items = []
            async for count in container.query_items(
                query=total_query,
                enable_cross_partition_query=True
            ):
                total_items.append(count)
            
            total_count = total_items[0] if total_items else 0
            
            # Count expired items
            now = datetime.utcnow().isoformat()
            expired_query = "SELECT VALUE COUNT(1) FROM c WHERE c.expires_at < @now"
            parameters = [{"name": "@now", "value": now}]
            
            expired_items = []
            async for count in container.query_items(
                query=expired_query,
                parameters=parameters,
                enable_cross_partition_query=True
            ):
                expired_items.append(count)
            
            expired_count = expired_items[0] if expired_items else 0
            
            stats = {
                "total_items": total_count,
                "expired_items": expired_count,
                "active_items": total_count - expired_count,
                "timestamp": datetime.utcnow().isoformat(),
            }
            
            logger.info("Cache statistics", **stats)
            return stats
            
        except Exception as e:
            logger.error("Failed to get cache statistics", error=str(e))
            return {
                "total_items": 0,
                "expired_items": 0,
                "active_items": 0,
                "timestamp": datetime.utcnow().isoformat(),
                "error": str(e),
            }
