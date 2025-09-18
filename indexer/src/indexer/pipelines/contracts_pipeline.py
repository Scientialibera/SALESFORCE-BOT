"""Contracts processing pipeline for SharePoint document indexing."""

import asyncio
import logging
from typing import Dict, List, Optional, Set, Any, Tuple
from datetime import datetime
import json

from ..services.sharepoint_service import SharePointService
from ..services.document_extraction_service import DocumentExtractionService
from ..services.chunking_service import ChunkingService
from ..services.vector_store_service import VectorStoreService
from ..services.progress_service import ProgressService, ProgressMetric
from ..services.cdc_service import CDCService
from ..repositories.processed_files_repository import ProcessedFilesRepository
from ..repositories.contracts_text_repository import ContractsTextRepository
from ..models.job import Job, JobType, JobStatus, JobResult
from ..models.document import Document, DocumentStatus
from ..models.chunk import Chunk
from ..config.settings import Settings


logger = logging.getLogger(__name__)


class ContractsPipeline:
    """Pipeline for processing contracts and legal documents from SharePoint."""
    
    def __init__(self,
                 settings: Settings,
                 sharepoint_service: SharePointService,
                 extraction_service: DocumentExtractionService,
                 chunking_service: ChunkingService,
                 vector_store_service: VectorStoreService,
                 progress_service: ProgressService,
                 cdc_service: CDCService,
                 processed_files_repo: ProcessedFilesRepository,
                 contracts_text_repo: ContractsTextRepository):
        """Initialize the contracts pipeline."""
        self.settings = settings
        self.sharepoint_service = sharepoint_service
        self.extraction_service = extraction_service
        self.chunking_service = chunking_service
        self.vector_store_service = vector_store_service
        self.progress_service = progress_service
        self.cdc_service = cdc_service
        self.processed_files_repo = processed_files_repo
        self.contracts_text_repo = contracts_text_repo
        
        # Pipeline configuration
        self.batch_size = 10  # Process documents in batches
        self.max_retries = 3
        self.supported_extensions = {".pdf", ".docx", ".doc", ".txt"}
    
    async def run_full_indexing(self, 
                               account_filter: Set[str] = None,
                               force_reprocess: bool = False) -> JobResult:
        """Run full indexing of all SharePoint documents."""
        try:
            # Create job
            job = await self.progress_service.create_job(
                job_type=JobType.FULL_INDEX,
                description="Full SharePoint contracts indexing",
                metadata={
                    "account_filter": list(account_filter) if account_filter else None,
                    "force_reprocess": force_reprocess
                }
            )
            
            # Start job
            await self.progress_service.start_job(job.job_id)
            
            logger.info(f"Starting full indexing job {job.job_id}")
            
            try:
                # Step 1: Discover documents
                await self.progress_service.update_job_progress(
                    job.job_id, 
                    progress_percentage=5,
                    current_step="Discovering SharePoint documents"
                )
                
                documents = await self.sharepoint_service.discover_all_documents(
                    account_filter=account_filter
                )
                
                await self.progress_service.record_metric(
                    job.job_id,
                    ProgressMetric.DOCUMENTS_DISCOVERED,
                    len(documents)
                )
                
                if not documents:
                    result = JobResult(
                        success=True,
                        message="No documents found to process",
                        documents_processed=0,
                        chunks_created=0,
                        chunks_indexed=0
                    )
                    await self.progress_service.complete_job(job.job_id, result)
                    return result
                
                # Filter out unsupported file types
                supported_documents = [
                    doc for doc in documents 
                    if any(doc["name"].lower().endswith(ext) for ext in self.supported_extensions)
                ]
                
                logger.info(f"Found {len(supported_documents)} supported documents out of {len(documents)} total")
                
                # Step 2: Process documents in batches
                await self.progress_service.update_job_progress(
                    job.job_id,
                    progress_percentage=10,
                    current_step="Processing documents"
                )
                
                total_processed = 0
                total_chunks_created = 0
                total_chunks_indexed = 0
                total_errors = 0
                
                for i in range(0, len(supported_documents), self.batch_size):
                    batch = supported_documents[i:i + self.batch_size]
                    
                    # Process batch
                    batch_result = await self._process_document_batch(
                        job.job_id,
                        batch,
                        force_reprocess
                    )
                    
                    total_processed += batch_result["processed"]
                    total_chunks_created += batch_result["chunks_created"]
                    total_chunks_indexed += batch_result["chunks_indexed"]
                    total_errors += batch_result["errors"]
                    
                    # Update progress
                    progress = 10 + (80 * (i + len(batch)) / len(supported_documents))
                    await self.progress_service.update_job_progress(
                        job.job_id,
                        progress_percentage=progress,
                        current_step=f"Processed {total_processed}/{len(supported_documents)} documents"
                    )
                
                # Step 3: Finalize
                await self.progress_service.update_job_progress(
                    job.job_id,
                    progress_percentage=95,
                    current_step="Finalizing indexing"
                )
                
                # Record final metrics
                await self.progress_service.record_metric(job.job_id, ProgressMetric.DOCUMENTS_PROCESSED, total_processed)
                await self.progress_service.record_metric(job.job_id, ProgressMetric.CHUNKS_CREATED, total_chunks_created)
                await self.progress_service.record_metric(job.job_id, ProgressMetric.CHUNKS_INDEXED, total_chunks_indexed)
                await self.progress_service.record_metric(job.job_id, ProgressMetric.ERRORS_ENCOUNTERED, total_errors)
                
                # Complete job
                result = JobResult(
                    success=True,
                    message=f"Successfully processed {total_processed} documents",
                    documents_processed=total_processed,
                    chunks_created=total_chunks_created,
                    chunks_indexed=total_chunks_indexed,
                    errors_encountered=total_errors
                )
                
                await self.progress_service.complete_job(job.job_id, result)
                
                logger.info(f"Completed full indexing job {job.job_id}: {result.message}")
                
                return result
                
            except Exception as e:
                error_msg = f"Full indexing failed: {str(e)}"
                logger.error(error_msg)
                await self.progress_service.complete_job(job.job_id, error_message=error_msg)
                raise
                
        except Exception as e:
            logger.error(f"Failed to run full indexing: {e}")
            raise
    
    async def run_incremental_indexing(self, 
                                     account_filter: Set[str] = None) -> JobResult:
        """Run incremental indexing based on CDC changes."""
        try:
            # Create job
            job = await self.progress_service.create_job(
                job_type=JobType.INCREMENTAL_INDEX,
                description="Incremental SharePoint contracts indexing",
                metadata={
                    "account_filter": list(account_filter) if account_filter else None
                }
            )
            
            # Start job
            await self.progress_service.start_job(job.job_id)
            
            logger.info(f"Starting incremental indexing job {job.job_id}")
            
            try:
                # Step 1: Scan for changes
                await self.progress_service.update_job_progress(
                    job.job_id,
                    progress_percentage=10,
                    current_step="Scanning for document changes"
                )
                
                changes = await self.cdc_service.scan_for_changes(account_filter)
                
                if not changes:
                    result = JobResult(
                        success=True,
                        message="No changes detected",
                        documents_processed=0,
                        chunks_created=0,
                        chunks_indexed=0
                    )
                    await self.progress_service.complete_job(job.job_id, result)
                    return result
                
                logger.info(f"Found {len(changes)} document changes")
                
                # Step 2: Process changes
                await self.progress_service.update_job_progress(
                    job.job_id,
                    progress_percentage=20,
                    current_step="Processing document changes"
                )
                
                total_processed = 0
                total_chunks_created = 0
                total_chunks_indexed = 0
                total_errors = 0
                
                for i, change in enumerate(changes):
                    try:
                        result = await self._process_change(change)
                        
                        total_processed += 1 if result["success"] else 0
                        total_chunks_created += result.get("chunks_created", 0)
                        total_chunks_indexed += result.get("chunks_indexed", 0)
                        
                        if result["success"]:
                            await self.cdc_service.mark_change_processed(change)
                        else:
                            total_errors += 1
                        
                    except Exception as e:
                        logger.error(f"Failed to process change {change.file_id}: {e}")
                        total_errors += 1
                    
                    # Update progress
                    progress = 20 + (70 * (i + 1) / len(changes))
                    await self.progress_service.update_job_progress(
                        job.job_id,
                        progress_percentage=progress,
                        current_step=f"Processed {i + 1}/{len(changes)} changes"
                    )
                
                # Record final metrics
                await self.progress_service.record_metric(job.job_id, ProgressMetric.DOCUMENTS_PROCESSED, total_processed)
                await self.progress_service.record_metric(job.job_id, ProgressMetric.CHUNKS_CREATED, total_chunks_created)
                await self.progress_service.record_metric(job.job_id, ProgressMetric.CHUNKS_INDEXED, total_chunks_indexed)
                await self.progress_service.record_metric(job.job_id, ProgressMetric.ERRORS_ENCOUNTERED, total_errors)
                
                # Complete job
                result = JobResult(
                    success=True,
                    message=f"Successfully processed {total_processed} changes",
                    documents_processed=total_processed,
                    chunks_created=total_chunks_created,
                    chunks_indexed=total_chunks_indexed,
                    errors_encountered=total_errors
                )
                
                await self.progress_service.complete_job(job.job_id, result)
                
                logger.info(f"Completed incremental indexing job {job.job_id}: {result.message}")
                
                return result
                
            except Exception as e:
                error_msg = f"Incremental indexing failed: {str(e)}"
                logger.error(error_msg)
                await self.progress_service.complete_job(job.job_id, error_message=error_msg)
                raise
                
        except Exception as e:
            logger.error(f"Failed to run incremental indexing: {e}")
            raise
    
    async def _process_document_batch(self, 
                                    job_id: str,
                                    documents: List[Dict[str, Any]],
                                    force_reprocess: bool = False) -> Dict[str, int]:
        """Process a batch of documents."""
        batch_result = {
            "processed": 0,
            "chunks_created": 0,
            "chunks_indexed": 0,
            "errors": 0
        }
        
        for doc_info in documents:
            try:
                result = await self._process_single_document(doc_info, force_reprocess)
                
                if result["success"]:
                    batch_result["processed"] += 1
                    batch_result["chunks_created"] += result.get("chunks_created", 0)
                    batch_result["chunks_indexed"] += result.get("chunks_indexed", 0)
                else:
                    batch_result["errors"] += 1
                    
            except Exception as e:
                logger.error(f"Failed to process document {doc_info.get('id', 'unknown')}: {e}")
                batch_result["errors"] += 1
        
        return batch_result
    
    async def _process_single_document(self, 
                                     doc_info: Dict[str, Any],
                                     force_reprocess: bool = False) -> Dict[str, Any]:
        """Process a single document through the full pipeline."""
        file_id = doc_info["id"]
        
        try:
            # Check if already processed and not forcing reprocess
            if not force_reprocess:
                processed_file = await self.processed_files_repo.get_processed_file(file_id)
                if processed_file and processed_file.etag == doc_info.get("etag"):
                    logger.debug(f"Document {file_id} already processed, skipping")
                    return {"success": True, "chunks_created": 0, "chunks_indexed": 0}
            
            # Download document
            file_content = await self.sharepoint_service.download_document(
                doc_info["site_url"],
                doc_info["server_relative_url"]
            )
            
            if not file_content:
                logger.warning(f"Could not download document {file_id}")
                return {"success": False}
            
            # Create document object
            document = Document(
                document_id=file_id,
                title=doc_info["name"],
                file_path=doc_info["server_relative_url"],
                content_type=doc_info.get("content_type", "application/octet-stream"),
                file_size=len(file_content),
                owner_email=doc_info.get("owner_email"),
                account_id=doc_info.get("account_id"),
                department=doc_info.get("department"),
                project_name=doc_info.get("project_name"),
                site_url=doc_info["site_url"],
                status=DocumentStatus.PROCESSING,
                created_at=datetime.utcnow()
            )
            
            # Extract content
            extraction_result = await self.extraction_service.extract_content(
                file_content=file_content,
                file_name=doc_info["name"],
                content_type=doc_info.get("content_type")
            )
            
            if not extraction_result.success:
                logger.error(f"Content extraction failed for {file_id}: {extraction_result.error_message}")
                return {"success": False}
            
            # Update document with extracted content
            document.extracted_text = extraction_result.extracted_text
            document.page_count = extraction_result.page_count
            document.table_count = len(extraction_result.tables) if extraction_result.tables else 0
            document.key_value_pairs = extraction_result.key_value_pairs
            document.entities = extraction_result.entities
            
            # Save document to repository
            await self.contracts_text_repo.save_document(document)
            
            # Create chunks
            chunks = await self.chunking_service.create_chunks(
                text=extraction_result.extracted_text,
                document_id=file_id,
                document_metadata={
                    "title": document.title,
                    "account_id": document.account_id,
                    "owner_email": document.owner_email,
                    "department": document.department,
                    "project_name": document.project_name,
                    "content_type": document.content_type
                }
            )
            
            # Save chunks to repository
            for chunk in chunks:
                await self.contracts_text_repo.save_chunk(chunk)
            
            # Index chunks in vector store
            indexed_count, failed_count = await self.vector_store_service.index_chunks(chunks)
            
            # Update document status
            if failed_count == 0:
                document.status = DocumentStatus.COMPLETED
            else:
                document.status = DocumentStatus.FAILED
                logger.warning(f"Failed to index {failed_count} chunks for document {file_id}")
            
            document.processing_completed_at = datetime.utcnow()
            await self.contracts_text_repo.save_document(document)
            
            # Update processed files tracking
            await self.processed_files_repo.mark_file_processed(
                file_id=file_id,
                file_path=doc_info["server_relative_url"],
                site_url=doc_info["site_url"],
                etag=doc_info.get("etag"),
                last_modified=doc_info.get("time_last_modified"),
                content_hash=self._calculate_content_hash(file_content)
            )
            
            logger.info(f"Successfully processed document {file_id}: {len(chunks)} chunks, {indexed_count} indexed")
            
            return {
                "success": True,
                "chunks_created": len(chunks),
                "chunks_indexed": indexed_count
            }
            
        except Exception as e:
            logger.error(f"Failed to process document {file_id}: {e}")
            return {"success": False}
    
    async def _process_change(self, change) -> Dict[str, Any]:
        """Process a CDC change entry."""
        try:
            if change.action == "deleted":
                # Handle deletion
                await self.vector_store_service.delete_chunks_by_document(change.file_id)
                await self.contracts_text_repo.delete_document(change.file_id)
                await self.processed_files_repo.remove_processed_file(change.file_id)
                
                logger.info(f"Processed deletion of document {change.file_id}")
                
                return {"success": True, "chunks_created": 0, "chunks_indexed": 0}
            
            elif change.action in ["added", "modified"]:
                # Get updated document info
                doc_info = await self.sharepoint_service.get_document_info(
                    change.site_url,
                    change.file_path
                )
                
                if not doc_info:
                    logger.warning(f"Could not get info for changed document {change.file_id}")
                    return {"success": False}
                
                # Process as new/updated document
                return await self._process_single_document(doc_info, force_reprocess=True)
            
            else:
                logger.warning(f"Unknown change action: {change.action}")
                return {"success": False}
                
        except Exception as e:
            logger.error(f"Failed to process change {change.file_id}: {e}")
            return {"success": False}
    
    def _calculate_content_hash(self, content: bytes) -> str:
        """Calculate hash of document content for change detection."""
        import hashlib
        return hashlib.sha256(content).hexdigest()
    
    async def cleanup_old_data(self, days_old: int = 90) -> Dict[str, int]:
        """Clean up old processed documents and chunks."""
        try:
            logger.info(f"Starting cleanup of data older than {days_old} days")
            
            cleanup_stats = {
                "documents_deleted": 0,
                "chunks_deleted": 0,
                "processed_files_cleaned": 0
            }
            
            # Clean up old processed files tracking
            processed_cleaned = await self.processed_files_repo.cleanup_old_entries(days_old)
            cleanup_stats["processed_files_cleaned"] = processed_cleaned
            
            # Clean up old documents and chunks from repository
            documents_cleaned = await self.contracts_text_repo.cleanup_old_documents(days_old)
            cleanup_stats["documents_deleted"] = documents_cleaned
            
            logger.info(f"Cleanup completed: {cleanup_stats}")
            
            return cleanup_stats
            
        except Exception as e:
            logger.error(f"Failed to cleanup old data: {e}")
            return {"documents_deleted": 0, "chunks_deleted": 0, "processed_files_cleaned": 0}
    
    async def get_pipeline_status(self) -> Dict[str, Any]:
        """Get current pipeline status and metrics."""
        try:
            # Get active jobs
            active_jobs = await self.progress_service.get_active_jobs()
            
            # Get system metrics
            system_metrics = await self.progress_service.get_system_metrics()
            
            # Get vector store statistics
            vector_stats = await self.vector_store_service.get_index_statistics()
            
            # Get CDC statistics
            cdc_stats = await self.cdc_service.get_change_statistics(hours_back=24)
            
            status = {
                "active_jobs": len(active_jobs),
                "active_job_details": [
                    {
                        "job_id": job.job_id,
                        "job_type": job.job_type.value,
                        "status": job.status.value,
                        "progress": job.progress_percentage,
                        "current_step": job.current_step,
                        "started_at": job.started_at.isoformat() if job.started_at else None
                    }
                    for job in active_jobs
                ],
                "system_metrics": system_metrics,
                "vector_store_stats": vector_stats,
                "cdc_stats": cdc_stats,
                "timestamp": datetime.utcnow().isoformat()
            }
            
            return status
            
        except Exception as e:
            logger.error(f"Failed to get pipeline status: {e}")
            return {"error": str(e)}
