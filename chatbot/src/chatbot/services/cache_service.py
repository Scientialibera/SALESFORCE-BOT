"""
Cache service for managing application-level caching.

This service provides high-level caching operations with smart keying
strategies and TTL management for different data types.
"""

import hashlib
import json
from typing import Any, Dict, List, Optional
import structlog

from chatbot.repositories.cache_repository import CacheRepository
from chatbot.models.rbac import RBACContext

logger = structlog.get_logger(__name__)


class CacheService:
    """Service for application-level caching operations."""
    
    def __init__(self, cache_repository: CacheRepository):
        """
        Initialize the cache service.
        
        Args:
            cache_repository: Cache repository for data persistence
        """
        self.cache_repository = cache_repository
        
        # Default TTL values for different cache types
        self.default_ttls = {
            "query_results": 1800,      # 30 minutes
            "embeddings": 86400,        # 24 hours
            "schema_metadata": 7200,    # 2 hours
            "user_permissions": 3600,   # 1 hour
            "account_data": 3600,       # 1 hour
            "prompts": 1800,           # 30 minutes
            "function_definitions": 7200,  # 2 hours
        }
    
    async def get_query_result(
        self,
        query: str,
        rbac_context: RBACContext,
        query_type: str = "sql"
    ) -> Optional[Any]:
        """
        Get cached query result.
        
        Args:
            query: The query string
            rbac_context: User's RBAC context
            query_type: Type of query (sql, graph, hybrid)
            
        Returns:
            Cached result or None if not found
        """
        cache_key = self._generate_query_key(query, rbac_context, query_type)
        
        try:
            result = await self.cache_repository.get(cache_key)
            
            if result:
                logger.debug(
                    "Query result cache hit",
                    user_id=rbac_context.user_id,
                    query_type=query_type,
                    cache_key=cache_key[:20] + "..."
                )
            
            return result
            
        except Exception as e:
            logger.error(
                "Failed to get cached query result",
                user_id=rbac_context.user_id,
                query_type=query_type,
                error=str(e)
            )
            return None
    
    async def set_query_result(
        self,
        query: str,
        result: Any,
        rbac_context: RBACContext,
        query_type: str = "sql",
        ttl_seconds: Optional[int] = None
    ) -> bool:
        """
        Cache query result.
        
        Args:
            query: The query string
            result: Query result to cache
            rbac_context: User's RBAC context
            query_type: Type of query (sql, graph, hybrid)
            ttl_seconds: Optional custom TTL
            
        Returns:
            True if cached successfully
        """
        cache_key = self._generate_query_key(query, rbac_context, query_type)
        ttl = ttl_seconds or self.default_ttls["query_results"]
        
        try:
            success = await self.cache_repository.set(cache_key, result, ttl)
            
            if success:
                logger.debug(
                    "Cached query result",
                    user_id=rbac_context.user_id,
                    query_type=query_type,
                    cache_key=cache_key[:20] + "...",
                    ttl_seconds=ttl
                )
            
            return success
            
        except Exception as e:
            logger.error(
                "Failed to cache query result",
                user_id=rbac_context.user_id,
                query_type=query_type,
                error=str(e)
            )
            return False
    
    async def get_embedding(self, text: str) -> Optional[List[float]]:
        """
        Get cached embedding for text.
        
        Args:
            text: Text to get embedding for
            
        Returns:
            Embedding vector or None if not found
        """
        cache_key = self._generate_embedding_key(text)
        
        try:
            embedding = await self.cache_repository.get(cache_key)
            
            if embedding:
                logger.debug("Embedding cache hit", text_hash=cache_key[:20] + "...")
            
            return embedding
            
        except Exception as e:
            logger.error("Failed to get cached embedding", error=str(e))
            return None
    
    async def set_embedding(
        self,
        text: str,
        embedding: List[float],
        ttl_seconds: Optional[int] = None
    ) -> bool:
        """
        Cache embedding for text.
        
        Args:
            text: Text the embedding represents
            embedding: Embedding vector
            ttl_seconds: Optional custom TTL
            
        Returns:
            True if cached successfully
        """
        cache_key = self._generate_embedding_key(text)
        ttl = ttl_seconds or self.default_ttls["embeddings"]
        
        try:
            success = await self.cache_repository.set(cache_key, embedding, ttl)
            
            if success:
                logger.debug(
                    "Cached embedding",
                    text_hash=cache_key[:20] + "...",
                    ttl_seconds=ttl
                )
            
            return success
            
        except Exception as e:
            logger.error("Failed to cache embedding", error=str(e))
            return False
    
    async def get_user_permissions(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Get cached user permissions.
        
        Args:
            user_id: User identifier
            
        Returns:
            Cached permissions or None if not found
        """
        cache_key = f"permissions:{user_id}"
        
        try:
            permissions = await self.cache_repository.get(cache_key)
            
            if permissions:
                logger.debug("User permissions cache hit", user_id=user_id)
            
            return permissions
            
        except Exception as e:
            logger.error("Failed to get cached permissions", user_id=user_id, error=str(e))
            return None
    
    async def set_user_permissions(
        self,
        user_id: str,
        permissions: Dict[str, Any],
        ttl_seconds: Optional[int] = None
    ) -> bool:
        """
        Cache user permissions.
        
        Args:
            user_id: User identifier
            permissions: User permissions data
            ttl_seconds: Optional custom TTL
            
        Returns:
            True if cached successfully
        """
        cache_key = f"permissions:{user_id}"
        ttl = ttl_seconds or self.default_ttls["user_permissions"]
        
        try:
            success = await self.cache_repository.set(cache_key, permissions, ttl)
            
            if success:
                logger.debug(
                    "Cached user permissions",
                    user_id=user_id,
                    ttl_seconds=ttl
                )
            
            return success
            
        except Exception as e:
            logger.error("Failed to cache permissions", user_id=user_id, error=str(e))
            return False
    
    async def invalidate_user_cache(self, user_id: str) -> bool:
        """
        Invalidate all cache entries for a user.
        
        Args:
            user_id: User identifier
            
        Returns:
            True if invalidation succeeded
        """
        try:
            # List of cache key patterns to invalidate
            patterns = [
                f"permissions:{user_id}",
                f"query:*:user:{user_id}:*",
                f"accounts:{user_id}",
            ]
            
            success_count = 0
            for pattern in patterns:
                if await self.cache_repository.delete(pattern):
                    success_count += 1
            
            logger.info(
                "Invalidated user cache",
                user_id=user_id,
                patterns_attempted=len(patterns),
                patterns_successful=success_count
            )
            
            return success_count > 0
            
        except Exception as e:
            logger.error("Failed to invalidate user cache", user_id=user_id, error=str(e))
            return False
    
    async def get_cache_stats(self) -> Dict[str, Any]:
        """
        Get cache usage statistics.
        
        Returns:
            Dictionary with cache statistics
        """
        try:
            stats = await self.cache_repository.get_cache_stats()
            
            # Add service-level metadata
            stats.update({
                "service": "cache_service",
                "default_ttls": self.default_ttls,
            })
            
            return stats
            
        except Exception as e:
            logger.error("Failed to get cache stats", error=str(e))
            return {"error": str(e)}
    
    def _generate_query_key(
        self,
        query: str,
        rbac_context: RBACContext,
        query_type: str
    ) -> str:
        """
        Generate cache key for query results.
        
        Args:
            query: The query string
            rbac_context: User's RBAC context
            query_type: Type of query
            
        Returns:
            Cache key string
        """
        # Create a deterministic key that includes user context
        key_data = {
            "query": query.strip().lower(),
            "user_id": rbac_context.user_id,
            "tenant_id": rbac_context.tenant_id,
            "roles": sorted(rbac_context.roles),
            "query_type": query_type,
        }
        
        # Create hash of the key data
        key_string = json.dumps(key_data, sort_keys=True)
        key_hash = hashlib.md5(key_string.encode()).hexdigest()
        
        return f"query:{query_type}:user:{rbac_context.user_id}:{key_hash}"
    
    def _generate_embedding_key(self, text: str) -> str:
        """
        Generate cache key for embeddings.
        
        Args:
            text: Text to generate key for
            
        Returns:
            Cache key string
        """
        # Use hash of normalized text
        normalized_text = text.strip().lower()
        text_hash = hashlib.md5(normalized_text.encode()).hexdigest()
        
        return f"embedding:{text_hash}"
    
    async def clear_expired_entries(self) -> int:
        """
        Clear expired cache entries.
        
        Returns:
            Number of entries cleared
        """
        try:
            cleared_count = await self.cache_repository.clear_expired()
            
            logger.info("Cleared expired cache entries", count=cleared_count)
            return cleared_count
            
        except Exception as e:
            logger.error("Failed to clear expired entries", error=str(e))
            return 0
