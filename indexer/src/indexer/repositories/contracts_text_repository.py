"""Repository for storing document content and chunks."""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from ..clients.cosmos_client import CosmosClient
from ..models.chunk import Chunk, ChunkMetadata
from ..models.document import Document


logger = logging.getLogger(__name__)


class ContractsTextRepository:
    """Repository for managing document content and text chunks."""
    
    DOCUMENTS_CONTAINER = "documents"
    CHUNKS_CONTAINER = "chunks"
    
    def __init__(self, cosmos_client: CosmosClient):
        """Initialize the repository."""
        self.cosmos_client = cosmos_client
    
    async def save_document_content(self, document: Document, content: str, 
                                   extracted_data: Dict[str, Any] = None) -> bool:
        """Save document content and metadata."""
        try:
            document_record = {
                "id": document.id,
                "sharepoint_id": document.sharepoint_id,
                "file_name": document.file_name,
                "file_path": document.file_path,
                "content": content,
                "content_length": len(content),
                "extracted_data": extracted_data or {},
                "status": document.status.value,
                "document_type": document.document_type.value,
                "file_size": document.file_size,
                "created_at": document.created_at.isoformat(),
                "processed_at": document.processed_at.isoformat() if document.processed_at else None,
                "metadata": document.metadata.model_dump() if document.metadata else {}
            }
            
            result = await self.cosmos_client.create_document(
                container_name=self.DOCUMENTS_CONTAINER,
                document=document_record
            )
            
            logger.debug(f"Saved document content for {document.file_name}")
            return result is not None
            
        except Exception as e:
            logger.error(f"Failed to save document content {document.file_name}: {e}")
            return False
    
    async def get_document_content(self, document_id: str) -> Optional[Dict[str, Any]]:
        """Get document content by ID."""
        try:
            return await self.cosmos_client.read_document(
                container_name=self.DOCUMENTS_CONTAINER,
                document_id=document_id
            )
        except Exception as e:
            logger.error(f"Failed to get document content {document_id}: {e}")
            return None
    
    async def save_chunk(self, chunk: Chunk) -> bool:
        """Save a document chunk."""
        try:
            chunk_record = {
                "id": chunk.id,
                "document_id": chunk.document_id,
                "chunk_index": chunk.chunk_index,
                "text": chunk.text,
                "title": chunk.title,
                "start_offset": chunk.start_offset,
                "end_offset": chunk.end_offset,
                "length": chunk.length,
                "embedding": chunk.embedding,
                "embedding_model": chunk.embedding_model,
                "tags": chunk.tags,
                "entities": chunk.entities,
                "created_at": chunk.created_at.isoformat(),
                "updated_at": chunk.updated_at.isoformat() if chunk.updated_at else None,
                "metadata": chunk.metadata.model_dump()
            }
            
            result = await self.cosmos_client.create_document(
                container_name=self.CHUNKS_CONTAINER,
                document=chunk_record,
                partition_key="/document_id"
            )
            
            logger.debug(f"Saved chunk {chunk.id} for document {chunk.document_id}")
            return result is not None
            
        except Exception as e:
            logger.error(f"Failed to save chunk {chunk.id}: {e}")
            return False
    
    async def save_chunks_batch(self, chunks: List[Chunk]) -> int:
        """Save multiple chunks in batch."""
        try:
            chunk_records = []
            for chunk in chunks:
                chunk_record = {
                    "id": chunk.id,
                    "document_id": chunk.document_id,
                    "chunk_index": chunk.chunk_index,
                    "text": chunk.text,
                    "title": chunk.title,
                    "start_offset": chunk.start_offset,
                    "end_offset": chunk.end_offset,
                    "length": chunk.length,
                    "embedding": chunk.embedding,
                    "embedding_model": chunk.embedding_model,
                    "tags": chunk.tags,
                    "entities": chunk.entities,
                    "created_at": chunk.created_at.isoformat(),
                    "updated_at": chunk.updated_at.isoformat() if chunk.updated_at else None,
                    "metadata": chunk.metadata.model_dump()
                }
                chunk_records.append(chunk_record)
            
            results = await self.cosmos_client.batch_create_documents(
                container_name=self.CHUNKS_CONTAINER,
                documents=chunk_records,
                partition_key="/document_id"
            )
            
            success_count = len(results)
            logger.info(f"Saved {success_count} chunks in batch")
            return success_count
            
        except Exception as e:
            logger.error(f"Failed to save chunks batch: {e}")
            return 0
    
    async def get_chunk(self, chunk_id: str, document_id: str) -> Optional[Dict[str, Any]]:
        """Get a chunk by ID."""
        try:
            return await self.cosmos_client.read_document(
                container_name=self.CHUNKS_CONTAINER,
                document_id=chunk_id,
                partition_key_value=document_id
            )
        except Exception as e:
            logger.error(f"Failed to get chunk {chunk_id}: {e}")
            return None
    
    async def get_document_chunks(self, document_id: str) -> List[Dict[str, Any]]:
        """Get all chunks for a document."""
        try:
            query = "SELECT * FROM c WHERE c.document_id = @document_id ORDER BY c.chunk_index"
            parameters = [{"name": "@document_id", "value": document_id}]
            
            chunks = await self.cosmos_client.query_documents_list(
                container_name=self.CHUNKS_CONTAINER,
                query=query,
                parameters=parameters,
                partition_key="/document_id"
            )
            
            return chunks
            
        except Exception as e:
            logger.error(f"Failed to get chunks for document {document_id}: {e}")
            return []
    
    async def search_chunks_by_text(self, search_text: str, 
                                   account_id: str = None,
                                   limit: int = 50) -> List[Dict[str, Any]]:
        """Search chunks by text content."""
        try:
            # Build search query
            query = "SELECT * FROM c WHERE CONTAINS(LOWER(c.text), @search_text)"
            parameters = [{"name": "@search_text", "value": search_text.lower()}]
            
            # Add account filter if provided
            if account_id:
                query += " AND c.metadata.account_id = @account_id"
                parameters.append({"name": "@account_id", "value": account_id})
            
            query += " ORDER BY c.created_at DESC"
            
            results = await self.cosmos_client.query_documents_list(
                container_name=self.CHUNKS_CONTAINER,
                query=query,
                parameters=parameters,
                partition_key="/document_id",
                max_items=limit
            )
            
            return results
            
        except Exception as e:
            logger.error(f"Failed to search chunks by text: {e}")
            return []
    
    async def get_chunks_by_entity(self, entity_type: str, entity_text: str,
                                  limit: int = 50) -> List[Dict[str, Any]]:
        """Get chunks containing specific entities."""
        try:
            query = """
                SELECT * FROM c 
                WHERE EXISTS(
                    SELECT VALUE e 
                    FROM e IN c.entities 
                    WHERE e.type = @entity_type AND e.text = @entity_text
                )
                ORDER BY c.created_at DESC
            """
            parameters = [
                {"name": "@entity_type", "value": entity_type},
                {"name": "@entity_text", "value": entity_text}
            ]
            
            results = await self.cosmos_client.query_documents_list(
                container_name=self.CHUNKS_CONTAINER,
                query=query,
                parameters=parameters,
                partition_key="/document_id",
                max_items=limit
            )
            
            return results
            
        except Exception as e:
            logger.error(f"Failed to get chunks by entity: {e}")
            return []
    
    async def get_chunks_by_account(self, account_id: str,
                                   limit: int = 100) -> List[Dict[str, Any]]:
        """Get chunks for a specific account."""
        try:
            query = "SELECT * FROM c WHERE c.metadata.account_id = @account_id ORDER BY c.created_at DESC"
            parameters = [{"name": "@account_id", "value": account_id}]
            
            results = await self.cosmos_client.query_documents_list(
                container_name=self.CHUNKS_CONTAINER,
                query=query,
                parameters=parameters,
                partition_key="/document_id",
                max_items=limit
            )
            
            return results
            
        except Exception as e:
            logger.error(f"Failed to get chunks by account {account_id}: {e}")
            return []
    
    async def update_chunk_embedding(self, chunk_id: str, document_id: str,
                                   embedding: List[float], model: str) -> bool:
        """Update chunk embedding."""
        try:
            # Get existing chunk
            chunk_data = await self.get_chunk(chunk_id, document_id)
            if not chunk_data:
                logger.warning(f"Chunk {chunk_id} not found for embedding update")
                return False
            
            # Update embedding fields
            chunk_data["embedding"] = embedding
            chunk_data["embedding_model"] = model
            chunk_data["updated_at"] = datetime.utcnow().isoformat()
            
            result = await self.cosmos_client.update_document(
                container_name=self.CHUNKS_CONTAINER,
                document=chunk_data
            )
            
            logger.debug(f"Updated embedding for chunk {chunk_id}")
            return result is not None
            
        except Exception as e:
            logger.error(f"Failed to update chunk embedding {chunk_id}: {e}")
            return False
    
    async def delete_document_content(self, document_id: str) -> bool:
        """Delete document content and all its chunks."""
        try:
            # Delete document content
            doc_deleted = await self.cosmos_client.delete_document(
                container_name=self.DOCUMENTS_CONTAINER,
                document_id=document_id
            )
            
            # Delete all chunks for the document
            chunks = await self.get_document_chunks(document_id)
            chunks_deleted = 0
            
            for chunk in chunks:
                success = await self.cosmos_client.delete_document(
                    container_name=self.CHUNKS_CONTAINER,
                    document_id=chunk["id"],
                    partition_key_value=document_id
                )
                if success:
                    chunks_deleted += 1
            
            logger.info(f"Deleted document {document_id} and {chunks_deleted} chunks")
            return doc_deleted
            
        except Exception as e:
            logger.error(f"Failed to delete document content {document_id}: {e}")
            return False
    
    async def get_content_statistics(self) -> Dict[str, Any]:
        """Get content statistics."""
        try:
            stats = {}
            
            # Document count
            doc_count = await self.cosmos_client.get_document_count(self.DOCUMENTS_CONTAINER)
            stats["document_count"] = doc_count
            
            # Chunk count
            chunk_count = await self.cosmos_client.get_document_count(self.CHUNKS_CONTAINER)
            stats["chunk_count"] = chunk_count
            
            # Average chunks per document
            if doc_count > 0:
                stats["avg_chunks_per_document"] = chunk_count / doc_count
            else:
                stats["avg_chunks_per_document"] = 0
            
            # Content size statistics
            query = """
                SELECT VALUE {
                    "total_content_length": SUM(c.content_length),
                    "avg_content_length": AVG(c.content_length),
                    "max_content_length": MAX(c.content_length)
                }
                FROM c
            """
            
            results = await self.cosmos_client.query_documents_list(
                container_name=self.DOCUMENTS_CONTAINER,
                query=query,
                max_items=1
            )
            
            if results:
                stats.update(results[0])
            
            # Chunk size statistics
            query = """
                SELECT VALUE {
                    "avg_chunk_length": AVG(c.length),
                    "max_chunk_length": MAX(c.length),
                    "min_chunk_length": MIN(c.length)
                }
                FROM c
            """
            
            results = await self.cosmos_client.query_documents_list(
                container_name=self.CHUNKS_CONTAINER,
                query=query,
                max_items=1
            )
            
            if results:
                stats.update(results[0])
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to get content statistics: {e}")
            return {}
    
    async def get_documents_by_date_range(self, start_date: datetime, 
                                         end_date: datetime) -> List[Dict[str, Any]]:
        """Get documents processed within a date range."""
        try:
            query = """
                SELECT * FROM c 
                WHERE c.processed_at >= @start_date AND c.processed_at <= @end_date
                ORDER BY c.processed_at DESC
            """
            parameters = [
                {"name": "@start_date", "value": start_date.isoformat()},
                {"name": "@end_date", "value": end_date.isoformat()}
            ]
            
            results = await self.cosmos_client.query_documents_list(
                container_name=self.DOCUMENTS_CONTAINER,
                query=query,
                parameters=parameters
            )
            
            return results
            
        except Exception as e:
            logger.error(f"Failed to get documents by date range: {e}")
            return []
    
    async def cleanup_old_content(self, days_old: int = 90) -> int:
        """Clean up old document content."""
        try:
            cutoff_date = (datetime.utcnow() - timedelta(days=days_old)).isoformat()
            
            # Find old documents
            query = "SELECT c.id FROM c WHERE c.created_at < @cutoff_date"
            parameters = [{"name": "@cutoff_date", "value": cutoff_date}]
            
            old_docs = await self.cosmos_client.query_documents_list(
                container_name=self.DOCUMENTS_CONTAINER,
                query=query,
                parameters=parameters,
                max_items=100  # Limit batch size
            )
            
            # Delete old documents and their chunks
            deleted_count = 0
            for doc in old_docs:
                success = await self.delete_document_content(doc["id"])
                if success:
                    deleted_count += 1
            
            logger.info(f"Cleaned up {deleted_count} old documents")
            return deleted_count
            
        except Exception as e:
            logger.error(f"Failed to cleanup old content: {e}")
            return 0
