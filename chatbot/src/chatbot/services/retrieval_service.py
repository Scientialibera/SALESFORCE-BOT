"""
Retrieval service for embedding-based search and context retrieval.

This service handles vector similarity search, document retrieval,
and context building for the semantic kernel agents.
"""

from typing import Any, Dict, List, Optional, Tuple
import numpy as np
from datetime import datetime
import structlog

from chatbot.clients.aoai_client import AOAIClient
from chatbot.clients.cosmos_client import CosmosDBClient
from chatbot.models.rbac import RBACContext
from chatbot.services.cache_service import CacheService
from chatbot.utils.embeddings import EmbeddingUtils

logger = structlog.get_logger(__name__)


class RetrievalService:
    """Service for document retrieval and context building."""
    
    def __init__(
        self,
        aoai_client: AOAIClient,
        cosmos_client: CosmosDBClient,
        cache_service: CacheService,
        embedding_utils: EmbeddingUtils
    ):
        """
        Initialize the retrieval service.
        
        Args:
            aoai_client: Azure OpenAI client for embeddings
            cosmos_client: Cosmos DB client for vector storage
            cache_service: Cache service for performance
            embedding_utils: Utilities for embedding operations
        """
        self.aoai_client = aoai_client
        self.cosmos_client = cosmos_client
        self.cache_service = cache_service
        self.embedding_utils = embedding_utils
        
        # Configuration
        self.vector_database = "vector_store"
        self.chunks_container = "chunks"
        self.similarity_threshold = 0.7
        self.max_context_tokens = 4000
    
    async def semantic_search(
        self,
        query: str,
        rbac_context: RBACContext,
        top_k: int = 10,
        filters: Optional[Dict[str, Any]] = None,
        include_metadata: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Perform semantic search using vector similarity.
        
        Args:
            query: Search query
            rbac_context: User's RBAC context
            top_k: Number of results to return
            filters: Optional search filters
            include_metadata: Whether to include chunk metadata
            
        Returns:
            List of matching chunks with similarity scores
        """
        try:
            # Check cache first
            cache_key = f"semantic_search:{query}:{rbac_context.user_id}:{top_k}"
            cached_results = await self.cache_service.get(cache_key)
            if cached_results:
                logger.debug(
                    "Semantic search cache hit",
                    query=query,
                    user_id=rbac_context.user_id
                )
                return cached_results
            
            # Generate query embedding
            query_embedding = await self.aoai_client.create_embedding(query)
            
            # Build search filters with RBAC
            search_filters = self._build_search_filters(rbac_context, filters)
            
            # Perform vector search
            results = await self._vector_search(
                query_embedding,
                top_k=top_k,
                filters=search_filters
            )
            
            # Post-process results
            processed_results = []
            for result in results:
                if result["similarity_score"] >= self.similarity_threshold:
                    processed_result = {
                        "chunk_id": result["id"],
                        "content": result["content"],
                        "similarity_score": result["similarity_score"],
                        "source": result.get("source", ""),
                        "page_number": result.get("page_number"),
                        "chunk_index": result.get("chunk_index")
                    }
                    
                    if include_metadata:
                        processed_result["metadata"] = result.get("metadata", {})
                    
                    processed_results.append(processed_result)
            
            # Cache results
            await self.cache_service.set(
                cache_key, 
                processed_results, 
                ttl_seconds=300  # 5 minutes
            )
            
            logger.info(
                "Semantic search completed",
                query=query,
                user_id=rbac_context.user_id,
                results_count=len(processed_results),
                top_k=top_k
            )
            
            return processed_results
            
        except Exception as e:
            logger.error(
                "Semantic search failed",
                query=query,
                user_id=rbac_context.user_id,
                error=str(e)
            )
            raise
    
    async def get_relevant_context(
        self,
        query: str,
        rbac_context: RBACContext,
        max_tokens: Optional[int] = None,
        context_type: str = "general"
    ) -> Dict[str, Any]:
        """
        Get relevant context for a query, formatted for LLM consumption.
        
        Args:
            query: User query
            rbac_context: User's RBAC context
            max_tokens: Maximum tokens in context
            context_type: Type of context needed ("sql", "graph", "general")
            
        Returns:
            Formatted context with sources
        """
        try:
            max_tokens = max_tokens or self.max_context_tokens
            
            # Get relevant chunks
            chunks = await self.semantic_search(
                query,
                rbac_context,
                top_k=20,  # Get more chunks to select from
                filters={"content_type": context_type} if context_type != "general" else None
            )
            
            # Build context within token limit
            context_text, sources = self._build_context_text(chunks, max_tokens)
            
            # Generate context summary
            context_summary = await self._generate_context_summary(
                context_text, query
            )
            
            result = {
                "context_text": context_text,
                "context_summary": context_summary,
                "sources": sources,
                "chunks_used": len([c for c in chunks if c["chunk_id"] in [s["chunk_id"] for s in sources]]),
                "total_chunks_found": len(chunks),
                "query": query,
                "context_type": context_type
            }
            
            logger.info(
                "Context retrieval completed",
                query=query,
                user_id=rbac_context.user_id,
                chunks_used=result["chunks_used"],
                context_tokens=len(context_text.split())
            )
            
            return result
            
        except Exception as e:
            logger.error(
                "Context retrieval failed",
                query=query,
                user_id=rbac_context.user_id,
                error=str(e)
            )
            raise
    
    async def hybrid_search(
        self,
        query: str,
        rbac_context: RBACContext,
        top_k: int = 10,
        semantic_weight: float = 0.7,
        keyword_weight: float = 0.3
    ) -> List[Dict[str, Any]]:
        """
        Perform hybrid search combining semantic and keyword search.
        
        Args:
            query: Search query
            rbac_context: User's RBAC context
            top_k: Number of results to return
            semantic_weight: Weight for semantic search
            keyword_weight: Weight for keyword search
            
        Returns:
            List of hybrid search results
        """
        try:
            # Perform semantic search
            semantic_results = await self.semantic_search(
                query, rbac_context, top_k=top_k * 2
            )
            
            # Perform keyword search
            keyword_results = await self._keyword_search(
                query, rbac_context, top_k=top_k * 2
            )
            
            # Combine and re-rank results
            combined_results = self._combine_search_results(
                semantic_results,
                keyword_results,
                semantic_weight,
                keyword_weight
            )
            
            # Return top k results
            final_results = combined_results[:top_k]
            
            logger.info(
                "Hybrid search completed",
                query=query,
                user_id=rbac_context.user_id,
                semantic_results=len(semantic_results),
                keyword_results=len(keyword_results),
                final_results=len(final_results)
            )
            
            return final_results
            
        except Exception as e:
            logger.error(
                "Hybrid search failed",
                query=query,
                user_id=rbac_context.user_id,
                error=str(e)
            )
            raise
    
    async def get_document_chunks(
        self,
        document_id: str,
        rbac_context: RBACContext,
        page_number: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Get all chunks for a specific document.
        
        Args:
            document_id: Document identifier
            rbac_context: User's RBAC context
            page_number: Optional specific page number
            
        Returns:
            List of document chunks
        """
        try:
            # Build query filters
            filters = {
                "document_id": document_id,
                "tenant_id": rbac_context.tenant_id
            }
            
            if page_number is not None:
                filters["page_number"] = page_number
            
            # Query chunks
            chunks_container = self.cosmos_client.get_container(
                self.vector_database, self.chunks_container
            )
            
            query = "SELECT * FROM c WHERE "
            conditions = []
            parameters = []
            
            for key, value in filters.items():
                conditions.append(f"c.{key} = @{key}")
                parameters.append({"name": f"@{key}", "value": value})
            
            query += " AND ".join(conditions)
            query += " ORDER BY c.chunk_index ASC"
            
            chunks = []
            async for item in chunks_container.query_items(
                query=query,
                parameters=parameters,
                enable_cross_partition_query=True
            ):
                chunks.append(item)
            
            logger.info(
                "Document chunks retrieved",
                document_id=document_id,
                user_id=rbac_context.user_id,
                chunks_count=len(chunks),
                page_number=page_number
            )
            
            return chunks
            
        except Exception as e:
            logger.error(
                "Failed to get document chunks",
                document_id=document_id,
                user_id=rbac_context.user_id,
                error=str(e)
            )
            raise
    
    async def _vector_search(
        self,
        query_embedding: List[float],
        top_k: int,
        filters: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Perform vector similarity search in Cosmos DB.
        
        Args:
            query_embedding: Query vector
            top_k: Number of results to return
            filters: Search filters
            
        Returns:
            List of similar documents
        """
        try:
            chunks_container = self.cosmos_client.get_container(
                self.vector_database, self.chunks_container
            )
            
            # Build vector search query
            # Note: This is a simplified implementation
            # In production, you'd use Cosmos DB's vector search capabilities
            
            # For now, we'll use a basic similarity calculation
            # In real implementation, use Cosmos DB vector search API
            
            query = "SELECT * FROM c"
            if filters:
                conditions = []
                parameters = []
                for key, value in filters.items():
                    conditions.append(f"c.{key} = @{key}")
                    parameters.append({"name": f"@{key}", "value": value})
                
                if conditions:
                    query += " WHERE " + " AND ".join(conditions)
            
            all_chunks = []
            async for item in chunks_container.query_items(
                query=query,
                parameters=parameters if filters else None,
                enable_cross_partition_query=True
            ):
                all_chunks.append(item)
            
            # Calculate similarities
            results = []
            for chunk in all_chunks:
                if "embedding" in chunk:
                    similarity = self.embedding_utils.cosine_similarity(
                        query_embedding, chunk["embedding"]
                    )
                    chunk["similarity_score"] = similarity
                    results.append(chunk)
            
            # Sort by similarity and return top k
            results.sort(key=lambda x: x["similarity_score"], reverse=True)
            return results[:top_k]
            
        except Exception as e:
            logger.error("Vector search failed", error=str(e))
            raise
    
    async def _keyword_search(
        self,
        query: str,
        rbac_context: RBACContext,
        top_k: int
    ) -> List[Dict[str, Any]]:
        """
        Perform keyword-based search.
        
        Args:
            query: Search query
            rbac_context: User's RBAC context
            top_k: Number of results to return
            
        Returns:
            List of keyword search results
        """
        try:
            chunks_container = self.cosmos_client.get_container(
                self.vector_database, self.chunks_container
            )
            
            # Simple keyword search using CONTAINS
            query_words = query.lower().split()
            
            # Build search conditions
            search_conditions = []
            for word in query_words[:5]:  # Limit to first 5 words
                search_conditions.append(f"CONTAINS(LOWER(c.content), '{word}')")
            
            if not search_conditions:
                return []
            
            cosmos_query = f"""
                SELECT *, (
                    {' + '.join([f"(CONTAINS(LOWER(c.content), '{word}') ? 1 : 0)" for word in query_words[:5]])}
                ) as keyword_score 
                FROM c 
                WHERE c.tenant_id = @tenant_id 
                AND ({' OR '.join(search_conditions)})
                ORDER BY keyword_score DESC
            """
            
            parameters = [
                {"name": "@tenant_id", "value": rbac_context.tenant_id}
            ]
            
            results = []
            async for item in chunks_container.query_items(
                query=cosmos_query,
                parameters=parameters,
                enable_cross_partition_query=True
            ):
                item["similarity_score"] = item.get("keyword_score", 0) / len(query_words)
                results.append(item)
            
            return results[:top_k]
            
        except Exception as e:
            logger.error("Keyword search failed", error=str(e))
            return []
    
    def _build_search_filters(
        self,
        rbac_context: RBACContext,
        user_filters: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Build search filters including RBAC constraints.
        
        Args:
            rbac_context: User's RBAC context
            user_filters: User-provided filters
            
        Returns:
            Combined filters
        """
        filters = {
            "tenant_id": rbac_context.tenant_id
        }
        
        # Add user-specific filters based on roles
        if "admin" not in rbac_context.roles:
            filters["access_level"] = "public"
        
        # Add user-provided filters
        if user_filters:
            filters.update(user_filters)
        
        return filters
    
    def _build_context_text(
        self,
        chunks: List[Dict[str, Any]],
        max_tokens: int
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Build context text from chunks within token limit.
        
        Args:
            chunks: List of relevant chunks
            max_tokens: Maximum tokens allowed
            
        Returns:
            Tuple of (context_text, sources)
        """
        context_parts = []
        sources = []
        current_tokens = 0
        
        for chunk in chunks:
            chunk_text = chunk["content"]
            chunk_tokens = len(chunk_text.split())
            
            if current_tokens + chunk_tokens > max_tokens:
                break
            
            context_parts.append(chunk_text)
            sources.append({
                "chunk_id": chunk["chunk_id"],
                "source": chunk.get("source", ""),
                "page_number": chunk.get("page_number"),
                "similarity_score": chunk["similarity_score"]
            })
            
            current_tokens += chunk_tokens
        
        context_text = "\n\n".join(context_parts)
        return context_text, sources
    
    def _combine_search_results(
        self,
        semantic_results: List[Dict[str, Any]],
        keyword_results: List[Dict[str, Any]],
        semantic_weight: float,
        keyword_weight: float
    ) -> List[Dict[str, Any]]:
        """
        Combine and re-rank semantic and keyword search results.
        
        Args:
            semantic_results: Results from semantic search
            keyword_results: Results from keyword search
            semantic_weight: Weight for semantic scores
            keyword_weight: Weight for keyword scores
            
        Returns:
            Combined and re-ranked results
        """
        # Create a mapping of chunk_id to results
        result_map = {}
        
        # Add semantic results
        for result in semantic_results:
            chunk_id = result["chunk_id"]
            result_map[chunk_id] = result.copy()
            result_map[chunk_id]["semantic_score"] = result["similarity_score"]
            result_map[chunk_id]["keyword_score"] = 0.0
        
        # Add/update with keyword results
        for result in keyword_results:
            chunk_id = result["chunk_id"]
            if chunk_id in result_map:
                result_map[chunk_id]["keyword_score"] = result["similarity_score"]
            else:
                result_copy = result.copy()
                result_copy["semantic_score"] = 0.0
                result_copy["keyword_score"] = result["similarity_score"]
                result_map[chunk_id] = result_copy
        
        # Calculate combined scores
        for chunk_id, result in result_map.items():
            combined_score = (
                result["semantic_score"] * semantic_weight +
                result["keyword_score"] * keyword_weight
            )
            result["similarity_score"] = combined_score
        
        # Sort by combined score
        combined_results = list(result_map.values())
        combined_results.sort(key=lambda x: x["similarity_score"], reverse=True)
        
        return combined_results
    
    async def _generate_context_summary(
        self,
        context_text: str,
        query: str
    ) -> str:
        """
        Generate a summary of the retrieved context.
        
        Args:
            context_text: Full context text
            query: Original query
            
        Returns:
            Context summary
        """
        try:
            if len(context_text) < 500:
                return "Retrieved relevant context for the query."
            
            # Use Azure OpenAI to generate summary
            summary_prompt = f"""
            Summarize the following context in relation to the query: "{query}"
            
            Context:
            {context_text[:2000]}...
            
            Provide a brief summary (2-3 sentences) of what information is available:
            """
            
            summary = await self.aoai_client.complete_chat(
                messages=[{"role": "user", "content": summary_prompt}],
                max_tokens=150,
                temperature=0.3
            )
            
            return summary.strip()
            
        except Exception as e:
            logger.warning("Failed to generate context summary", error=str(e))
            return f"Retrieved {len(context_text.split())} words of relevant context."
