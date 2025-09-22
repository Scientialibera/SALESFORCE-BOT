"""Compatibility shim for CacheRepository used by older callers.

This minimal adapter delegates to the UnifiedDataService stored on
`app_state.unified_data_service`. It exists to avoid changing many
callsites during the transition.
"""
from typing import Any, Optional

from chatbot.app import app_state


class CacheRepository:
    async def get(self, key: str) -> Optional[Any]:
        uds = getattr(app_state, "unified_data_service", None)
        if not uds:
            return None
        # UnifiedDataService exposes get_query_result for keyed query cache
        return await uds.get_query_result(key, None) if hasattr(uds, "get_query_result") else None

    async def set(self, key: str, value: Any, ttl: int) -> bool:
        uds = getattr(app_state, "unified_data_service", None)
        if not uds:
            return False
        return await uds.set_query_result(key, value, None, ttl_seconds=ttl)

    async def delete(self, key: str) -> bool:
        uds = getattr(app_state, "unified_data_service", None)
        if not uds:
            return False
        # Best-effort: delete item by id
        try:
            return await uds._client.delete_item(container_name=uds._container, item_id=key, partition_key_value=uds._container)
        except Exception:
            return False
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
            database = await self.cosmos_client.get_database_client(self.database_name)
            self._container = database.get_container_client(self.container_name)
        return self._container

    def _partition_for_key(self, key: str) -> str:
        """
        Derive the user partition key value from cache key when storing
        cache items in a shared container that uses `/user_id` as the
        partition key. Keys created by the service include the user id in
        predictable positions for query results and permissions.

        Examples:
        - `query:sql:user:alice@example.com:<hash>` -> `alice@example.com`
        - `permissions:alice@example.com` -> `alice@example.com`
        - `embedding:<hash>` -> `system` (shared/system partition)

        Returns a partition key value string.
        """
        try:
            if key.startswith("query:"):
                # expected format: query:{type}:user:{user_id}:{hash}
                parts = key.split(":")
                # defensive check
                if len(parts) >= 4 and parts[2] == "user":
                    return parts[3]
            if key.startswith("permissions:"):
                # permissions:{user_id}
                return key.split(":", 1)[1]
        except Exception:
            pass
        # default to a system partition for keys that are not per-user
        return "system"
    
    async def get(self, key: str) -> Optional[Any]:
        """
        Get a cached value by key.
        
        Args:
            key: Cache key
            
        Returns:
            Cached value or None if not found/expired
        """
        container = await self._get_container()
        partition_value = self._partition_for_key(key)

        # Try to read directly using the derived partition key. If any error occurs
        # (not only ResourceNotFound), fall back to a cross-partition query to find
        # the item. This makes the get operation more robust to partitioning/schema
        # mismatches in the container.
        try:
            # Read by id with the derived partition key value
            item = await container.read_item(
                item=key,
                partition_key=partition_value
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

        except Exception:
            # Fallback: attempt cross-partition query to find the item by id
            try:
                # Select the entire document as 'c' to avoid issues with reserved
                # keywords like 'value' in Cosmos SQL. Extract the document and return
                # its 'value' property.
                query = "SELECT c FROM c WHERE c.id = @id"
                parameters = [{"name": "@id", "value": key}]
                async for row in container.query_items(query=query, parameters=parameters):
                    item = row.get("c") if isinstance(row, dict) else row
                    if not item:
                        continue
                    if "expires_at" in item:
                        expires_at = datetime.fromisoformat(item["expires_at"])
                        if datetime.utcnow() > expires_at:
                            await self.delete(key)
                            return None
                    logger.debug("Cache hit (cross-partition)", key=key)
                    return item.get("value")
            except Exception as e:
                logger.debug("Cross-partition cache query failed", key=key, error=str(e))

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

            partition_value = self._partition_for_key(key)

            cache_item = {
                "id": key,
                "user_id": partition_value,
                "value": value,
                "created_at": datetime.utcnow().isoformat(),
                "expires_at": expires_at.isoformat(),
                "ttl": ttl_seconds,  # Cosmos DB TTL field
            }

            # Upsert using derived partition value (container partition is `/user_id` in unified schema)
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
            partition_value = self._partition_for_key(key)

            await container.delete_item(
                item=key,
                partition_key=partition_value
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
                parameters=parameters
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
                query=total_query
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
                parameters=parameters
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
