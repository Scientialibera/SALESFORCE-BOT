"""Repository for tracking processed files and their processing state."""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from ..clients.cosmos_client import CosmosClient
from ..models.document import Document, DocumentStatus, DocumentType


logger = logging.getLogger(__name__)


class ProcessedFilesRepository:
    """Repository for managing processed file records."""
    
    CONTAINER_NAME = "processed_files"
    
    def __init__(self, cosmos_client: CosmosClient):
        """Initialize the repository."""
        self.cosmos_client = cosmos_client
    
    async def get_processed_file(self, file_id: str) -> Optional[Dict[str, Any]]:
        """Get a processed file record by ID."""
        try:
            return await self.cosmos_client.read_document(
                container_name=self.CONTAINER_NAME,
                document_id=file_id
            )
        except Exception as e:
            logger.error(f"Failed to get processed file {file_id}: {e}")
            return None
    
    async def save_processed_file(self, document: Document) -> bool:
        """Save or update a processed file record."""
        try:
            processed_file = {
                "id": document.id,
                "sharepoint_id": document.sharepoint_id,
                "file_name": document.file_name,
                "file_path": document.file_path,
                "etag": document.etag,
                "last_modified": document.last_modified.isoformat() if document.last_modified else None,
                "content_hash": document.content_hash,
                "file_size": document.file_size,
                "status": document.status.value,
                "processed_at": document.processed_at.isoformat() if document.processed_at else None,
                "created_at": document.created_at.isoformat(),
                "updated_at": document.updated_at.isoformat() if document.updated_at else None,
                "processing_duration_ms": document.processing_duration_ms,
                "chunk_count": document.chunk_count,
                "error_message": document.error_message,
                "metadata": document.metadata.model_dump() if document.metadata else {}
            }
            
            result = await self.cosmos_client.create_document(
                container_name=self.CONTAINER_NAME,
                document=processed_file
            )
            
            logger.debug(f"Saved processed file record for {document.file_name}")
            return result is not None
            
        except Exception as e:
            logger.error(f"Failed to save processed file {document.file_name}: {e}")
            return False
    
    async def update_processing_status(self, file_id: str, status: DocumentStatus, 
                                     error_message: str = None,
                                     processing_duration_ms: int = None,
                                     chunk_count: int = None) -> bool:
        """Update the processing status of a file."""
        try:
            # Get existing record
            existing = await self.get_processed_file(file_id)
            if not existing:
                logger.warning(f"Processed file {file_id} not found for status update")
                return False
            
            # Update fields
            existing["status"] = status.value
            existing["updated_at"] = datetime.utcnow().isoformat()
            
            if status == DocumentStatus.COMPLETED:
                existing["processed_at"] = datetime.utcnow().isoformat()
            
            if error_message:
                existing["error_message"] = error_message
            
            if processing_duration_ms is not None:
                existing["processing_duration_ms"] = processing_duration_ms
            
            if chunk_count is not None:
                existing["chunk_count"] = chunk_count
            
            result = await self.cosmos_client.update_document(
                container_name=self.CONTAINER_NAME,
                document=existing
            )
            
            logger.debug(f"Updated processing status for {file_id} to {status.value}")
            return result is not None
            
        except Exception as e:
            logger.error(f"Failed to update processing status for {file_id}: {e}")
            return False
    
    async def is_file_processed(self, sharepoint_id: str, etag: str = None, 
                               last_modified: datetime = None) -> bool:
        """Check if a file has been processed (and is up to date)."""
        try:
            # Query by SharePoint ID
            query = "SELECT * FROM c WHERE c.sharepoint_id = @sharepoint_id"
            parameters = [{"name": "@sharepoint_id", "value": sharepoint_id}]
            
            results = await self.cosmos_client.query_documents_list(
                container_name=self.CONTAINER_NAME,
                query=query,
                parameters=parameters,
                max_items=1
            )
            
            if not results:
                return False
            
            processed_file = results[0]
            
            # Check if processing was successful
            if processed_file.get("status") != DocumentStatus.COMPLETED.value:
                return False
            
            # Check if file has been modified since processing
            if etag and processed_file.get("etag") != etag:
                return False
            
            if last_modified:
                processed_modified = processed_file.get("last_modified")
                if processed_modified:
                    processed_dt = datetime.fromisoformat(processed_modified)
                    if last_modified > processed_dt:
                        return False
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to check if file is processed {sharepoint_id}: {e}")
            return False
    
    async def get_files_by_status(self, status: DocumentStatus, 
                                 limit: int = 100) -> List[Dict[str, Any]]:
        """Get files by processing status."""
        try:
            query = "SELECT * FROM c WHERE c.status = @status ORDER BY c.updated_at DESC"
            parameters = [{"name": "@status", "value": status.value}]
            
            results = await self.cosmos_client.query_documents_list(
                container_name=self.CONTAINER_NAME,
                query=query,
                parameters=parameters,
                max_items=limit
            )
            
            return results
            
        except Exception as e:
            logger.error(f"Failed to get files by status {status.value}: {e}")
            return []
    
    async def get_failed_files(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get files that failed processing."""
        return await self.get_files_by_status(DocumentStatus.FAILED, limit)
    
    async def get_pending_files(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get files pending processing."""
        return await self.get_files_by_status(DocumentStatus.PENDING, limit)
    
    async def get_processing_statistics(self) -> Dict[str, Any]:
        """Get processing statistics."""
        try:
            stats = {}
            
            # Count by status
            for status in DocumentStatus:
                query = "SELECT VALUE COUNT(1) FROM c WHERE c.status = @status"
                parameters = [{"name": "@status", "value": status.value}]
                
                results = await self.cosmos_client.query_documents_list(
                    container_name=self.CONTAINER_NAME,
                    query=query,
                    parameters=parameters,
                    max_items=1
                )
                
                stats[f"{status.value}_count"] = results[0] if results else 0
            
            # Get total processing time
            query = """
                SELECT VALUE AVG(c.processing_duration_ms) 
                FROM c 
                WHERE c.status = @status AND c.processing_duration_ms != null
            """
            parameters = [{"name": "@status", "value": DocumentStatus.COMPLETED.value}]
            
            results = await self.cosmos_client.query_documents_list(
                container_name=self.CONTAINER_NAME,
                query=query,
                parameters=parameters,
                max_items=1
            )
            
            stats["avg_processing_time_ms"] = results[0] if results else 0
            
            # Get total chunk count
            query = """
                SELECT VALUE SUM(c.chunk_count) 
                FROM c 
                WHERE c.status = @status AND c.chunk_count != null
            """
            
            results = await self.cosmos_client.query_documents_list(
                container_name=self.CONTAINER_NAME,
                query=query,
                parameters=parameters,
                max_items=1
            )
            
            stats["total_chunks"] = results[0] if results else 0
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to get processing statistics: {e}")
            return {}
    
    async def cleanup_old_records(self, days_old: int = 30) -> int:
        """Clean up old processed file records."""
        try:
            cutoff_date = (datetime.utcnow() - timedelta(days=days_old)).isoformat()
            
            # Find old records
            query = """
                SELECT c.id 
                FROM c 
                WHERE c.created_at < @cutoff_date 
                AND c.status IN (@completed, @failed)
            """
            parameters = [
                {"name": "@cutoff_date", "value": cutoff_date},
                {"name": "@completed", "value": DocumentStatus.COMPLETED.value},
                {"name": "@failed", "value": DocumentStatus.FAILED.value}
            ]
            
            results = await self.cosmos_client.query_documents_list(
                container_name=self.CONTAINER_NAME,
                query=query,
                parameters=parameters,
                max_items=1000  # Limit batch size
            )
            
            # Delete old records
            deleted_count = 0
            for record in results:
                success = await self.cosmos_client.delete_document(
                    container_name=self.CONTAINER_NAME,
                    document_id=record["id"]
                )
                if success:
                    deleted_count += 1
            
            logger.info(f"Cleaned up {deleted_count} old processed file records")
            return deleted_count
            
        except Exception as e:
            logger.error(f"Failed to cleanup old records: {e}")
            return 0
    
    async def mark_for_reprocessing(self, file_ids: List[str]) -> int:
        """Mark files for reprocessing by resetting their status."""
        try:
            updated_count = 0
            
            for file_id in file_ids:
                success = await self.update_processing_status(
                    file_id=file_id,
                    status=DocumentStatus.PENDING,
                    error_message=None
                )
                if success:
                    updated_count += 1
            
            logger.info(f"Marked {updated_count} files for reprocessing")
            return updated_count
            
        except Exception as e:
            logger.error(f"Failed to mark files for reprocessing: {e}")
            return 0
    
    async def get_files_by_account(self, account_id: str, 
                                  limit: int = 100) -> List[Dict[str, Any]]:
        """Get processed files for a specific account."""
        try:
            query = "SELECT * FROM c WHERE c.metadata.account_id = @account_id ORDER BY c.updated_at DESC"
            parameters = [{"name": "@account_id", "value": account_id}]
            
            results = await self.cosmos_client.query_documents_list(
                container_name=self.CONTAINER_NAME,
                query=query,
                parameters=parameters,
                max_items=limit
            )
            
            return results
            
        except Exception as e:
            logger.error(f"Failed to get files by account {account_id}: {e}")
            return []
