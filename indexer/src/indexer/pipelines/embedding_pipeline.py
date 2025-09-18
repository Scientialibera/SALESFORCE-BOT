"""Embedding pipeline for generating and managing document embeddings."""

import asyncio
import logging
from typing import Dict, List, Optional, Set, Any, Tuple
from datetime import datetime
import json

from ..services.vector_store_service import VectorStoreService
from ..services.progress_service import ProgressService, ProgressMetric
from ..repositories.contracts_text_repository import ContractsTextRepository
from ..clients.aoai_client import AzureOpenAIClient
from ..models.job import Job, JobType, JobStatus, JobResult
from ..models.chunk import Chunk
from ..config.settings import Settings


logger = logging.getLogger(__name__)


class EmbeddingPipeline:
    """Pipeline for generating and updating embeddings for document chunks."""
    
    def __init__(self,
                 settings: Settings,
                 vector_store_service: VectorStoreService,
                 progress_service: ProgressService,
                 contracts_text_repo: ContractsTextRepository,
                 aoai_client: AzureOpenAIClient):
        """Initialize the embedding pipeline."""
        self.settings = settings
        self.vector_store_service = vector_store_service
        self.progress_service = progress_service
        self.contracts_text_repo = contracts_text_repo
        self.aoai_client = aoai_client
        
        # Pipeline configuration
        self.batch_size = 50  # Process embeddings in batches
        self.embedding_batch_size = 20  # Size for embedding generation batches
        self.max_retries = 3
    
    async def regenerate_all_embeddings(self, 
                                      embedding_model: str = None,
                                      account_filter: Set[str] = None) -> JobResult:
        """Regenerate embeddings for all chunks with a new model."""
        try:
            model_name = embedding_model or self.settings.azure_openai.embedding_model
            
            # Create job
            job = await self.progress_service.create_job(
                job_type=JobType.EMBEDDING_GENERATION,
                description=f"Regenerating embeddings with model {model_name}",
                metadata={
                    "embedding_model": model_name,
                    "account_filter": list(account_filter) if account_filter else None
                }
            )
            
            # Start job
            await self.progress_service.start_job(job.job_id)
            
            logger.info(f"Starting embedding regeneration job {job.job_id} with model {model_name}")
            
            try:
                # Step 1: Get all chunks that need embeddings
                await self.progress_service.update_job_progress(
                    job.job_id,
                    progress_percentage=5,
                    current_step="Loading chunks from repository"
                )
                
                chunks = await self._get_chunks_for_embedding(account_filter)
                
                if not chunks:
                    result = JobResult(
                        success=True,
                        message="No chunks found to process",
                        chunks_processed=0,
                        embeddings_generated=0
                    )
                    await self.progress_service.complete_job(job.job_id, result)
                    return result
                
                logger.info(f"Found {len(chunks)} chunks to process")
                
                # Step 2: Generate embeddings in batches
                await self.progress_service.update_job_progress(
                    job.job_id,
                    progress_percentage=10,
                    current_step="Generating embeddings"
                )
                
                total_processed = 0
                total_embeddings_generated = 0
                total_errors = 0
                
                for i in range(0, len(chunks), self.batch_size):
                    batch = chunks[i:i + self.batch_size]
                    
                    # Process batch
                    batch_result = await self._process_embedding_batch(
                        batch,
                        model_name
                    )
                    
                    total_processed += batch_result["processed"]
                    total_embeddings_generated += batch_result["embeddings_generated"]
                    total_errors += batch_result["errors"]
                    
                    # Update progress
                    progress = 10 + (80 * (i + len(batch)) / len(chunks))
                    await self.progress_service.update_job_progress(
                        job.job_id,
                        progress_percentage=progress,
                        current_step=f"Processed {total_processed}/{len(chunks)} chunks"
                    )
                
                # Step 3: Index updated chunks in vector store
                await self.progress_service.update_job_progress(
                    job.job_id,
                    progress_percentage=90,
                    current_step="Updating vector store index"
                )
                
                # Get chunks with new embeddings and index them
                updated_chunks = [chunk for chunk in chunks if chunk.embedding]
                
                if updated_chunks:
                    indexed_count, failed_count = await self.vector_store_service.index_chunks(updated_chunks)
                    
                    if failed_count > 0:
                        logger.warning(f"Failed to index {failed_count} chunks in vector store")
                
                # Record final metrics
                await self.progress_service.record_metric(job.job_id, ProgressMetric.CHUNKS_CREATED, total_processed)
                await self.progress_service.record_metric(job.job_id, ProgressMetric.CHUNKS_INDEXED, total_embeddings_generated)
                await self.progress_service.record_metric(job.job_id, ProgressMetric.ERRORS_ENCOUNTERED, total_errors)
                
                # Complete job
                result = JobResult(
                    success=True,
                    message=f"Successfully regenerated embeddings for {total_embeddings_generated} chunks",
                    chunks_processed=total_processed,
                    embeddings_generated=total_embeddings_generated,
                    errors_encountered=total_errors
                )
                
                await self.progress_service.complete_job(job.job_id, result)
                
                logger.info(f"Completed embedding regeneration job {job.job_id}: {result.message}")
                
                return result
                
            except Exception as e:
                error_msg = f"Embedding regeneration failed: {str(e)}"
                logger.error(error_msg)
                await self.progress_service.complete_job(job.job_id, error_message=error_msg)
                raise
                
        except Exception as e:
            logger.error(f"Failed to regenerate embeddings: {e}")
            raise
    
    async def update_missing_embeddings(self, 
                                      embedding_model: str = None,
                                      account_filter: Set[str] = None) -> JobResult:
        """Generate embeddings for chunks that don't have them."""
        try:
            model_name = embedding_model or self.settings.azure_openai.embedding_model
            
            # Create job
            job = await self.progress_service.create_job(
                job_type=JobType.EMBEDDING_GENERATION,
                description=f"Generating missing embeddings with model {model_name}",
                metadata={
                    "embedding_model": model_name,
                    "account_filter": list(account_filter) if account_filter else None,
                    "missing_only": True
                }
            )
            
            # Start job
            await self.progress_service.start_job(job.job_id)
            
            logger.info(f"Starting missing embeddings job {job.job_id}")
            
            try:
                # Get chunks without embeddings
                await self.progress_service.update_job_progress(
                    job.job_id,
                    progress_percentage=5,
                    current_step="Finding chunks without embeddings"
                )
                
                chunks = await self._get_chunks_without_embeddings(account_filter)
                
                if not chunks:
                    result = JobResult(
                        success=True,
                        message="All chunks already have embeddings",
                        chunks_processed=0,
                        embeddings_generated=0
                    )
                    await self.progress_service.complete_job(job.job_id, result)
                    return result
                
                logger.info(f"Found {len(chunks)} chunks without embeddings")
                
                # Generate embeddings
                total_processed = 0
                total_embeddings_generated = 0
                total_errors = 0
                
                for i in range(0, len(chunks), self.batch_size):
                    batch = chunks[i:i + self.batch_size]
                    
                    batch_result = await self._process_embedding_batch(
                        batch,
                        model_name
                    )
                    
                    total_processed += batch_result["processed"]
                    total_embeddings_generated += batch_result["embeddings_generated"]
                    total_errors += batch_result["errors"]
                    
                    # Update progress
                    progress = 5 + (85 * (i + len(batch)) / len(chunks))
                    await self.progress_service.update_job_progress(
                        job.job_id,
                        progress_percentage=progress,
                        current_step=f"Generated embeddings for {total_embeddings_generated}/{len(chunks)} chunks"
                    )
                
                # Index new embeddings
                updated_chunks = [chunk for chunk in chunks if chunk.embedding]
                
                if updated_chunks:
                    await self.progress_service.update_job_progress(
                        job.job_id,
                        progress_percentage=95,
                        current_step="Indexing new embeddings"
                    )
                    
                    indexed_count, failed_count = await self.vector_store_service.index_chunks(updated_chunks)
                    
                    if failed_count > 0:
                        logger.warning(f"Failed to index {failed_count} chunks")
                
                # Complete job
                result = JobResult(
                    success=True,
                    message=f"Generated embeddings for {total_embeddings_generated} chunks",
                    chunks_processed=total_processed,
                    embeddings_generated=total_embeddings_generated,
                    errors_encountered=total_errors
                )
                
                await self.progress_service.complete_job(job.job_id, result)
                
                logger.info(f"Completed missing embeddings job {job.job_id}: {result.message}")
                
                return result
                
            except Exception as e:
                error_msg = f"Missing embeddings generation failed: {str(e)}"
                logger.error(error_msg)
                await self.progress_service.complete_job(job.job_id, error_message=error_msg)
                raise
                
        except Exception as e:
            logger.error(f"Failed to update missing embeddings: {e}")
            raise
    
    async def validate_embeddings(self, 
                                embedding_model: str = None,
                                sample_size: int = 100) -> Dict[str, Any]:
        """Validate the quality and consistency of embeddings."""
        try:
            model_name = embedding_model or self.settings.azure_openai.embedding_model
            
            logger.info(f"Starting embedding validation with sample size {sample_size}")
            
            # Get random sample of chunks with embeddings
            chunks = await self._get_random_chunks_with_embeddings(sample_size)
            
            if not chunks:
                return {
                    "status": "no_data",
                    "message": "No chunks with embeddings found"
                }
            
            validation_results = {
                "total_chunks_sampled": len(chunks),
                "model_used": model_name,
                "validation_timestamp": datetime.utcnow().isoformat(),
                "issues_found": [],
                "statistics": {}
            }
            
            # Validate embedding dimensions
            expected_dimension = 1536  # OpenAI text-embedding-3-small/large dimension
            
            dimension_issues = 0
            null_embeddings = 0
            model_mismatches = 0
            
            for chunk in chunks:
                if not chunk.embedding:
                    null_embeddings += 1
                    validation_results["issues_found"].append({
                        "chunk_id": chunk.chunk_id,
                        "issue": "null_embedding",
                        "description": "Chunk has no embedding vector"
                    })
                    continue
                
                if len(chunk.embedding) != expected_dimension:
                    dimension_issues += 1
                    validation_results["issues_found"].append({
                        "chunk_id": chunk.chunk_id,
                        "issue": "dimension_mismatch",
                        "description": f"Expected {expected_dimension} dimensions, got {len(chunk.embedding)}"
                    })
                
                if chunk.embedding_model != model_name:
                    model_mismatches += 1
                    validation_results["issues_found"].append({
                        "chunk_id": chunk.chunk_id,
                        "issue": "model_mismatch",
                        "description": f"Expected model {model_name}, got {chunk.embedding_model}"
                    })
            
            # Calculate statistics
            valid_embeddings = len(chunks) - null_embeddings - dimension_issues
            
            validation_results["statistics"] = {
                "valid_embeddings": valid_embeddings,
                "null_embeddings": null_embeddings,
                "dimension_issues": dimension_issues,
                "model_mismatches": model_mismatches,
                "validation_score": valid_embeddings / len(chunks) if chunks else 0
            }
            
            # Determine overall status
            if null_embeddings == 0 and dimension_issues == 0:
                validation_results["status"] = "healthy"
            elif null_embeddings > len(chunks) * 0.1 or dimension_issues > 0:
                validation_results["status"] = "critical"
            else:
                validation_results["status"] = "warning"
            
            logger.info(f"Embedding validation completed: {validation_results['status']}")
            
            return validation_results
            
        except Exception as e:
            logger.error(f"Failed to validate embeddings: {e}")
            return {
                "status": "error",
                "message": str(e),
                "validation_timestamp": datetime.utcnow().isoformat()
            }
    
    async def _get_chunks_for_embedding(self, account_filter: Set[str] = None) -> List[Chunk]:
        """Get all chunks that need embeddings."""
        try:
            # Build query based on account filter
            if account_filter:
                chunks = []
                for account_id in account_filter:
                    account_chunks = await self.contracts_text_repo.get_chunks_by_account(account_id)
                    chunks.extend(account_chunks)
            else:
                chunks = await self.contracts_text_repo.get_all_chunks()
            
            return chunks
            
        except Exception as e:
            logger.error(f"Failed to get chunks for embedding: {e}")
            return []
    
    async def _get_chunks_without_embeddings(self, account_filter: Set[str] = None) -> List[Chunk]:
        """Get chunks that don't have embeddings."""
        try:
            all_chunks = await self._get_chunks_for_embedding(account_filter)
            
            # Filter out chunks that already have embeddings
            chunks_without_embeddings = [
                chunk for chunk in all_chunks 
                if not chunk.embedding or len(chunk.embedding) == 0
            ]
            
            return chunks_without_embeddings
            
        except Exception as e:
            logger.error(f"Failed to get chunks without embeddings: {e}")
            return []
    
    async def _get_random_chunks_with_embeddings(self, sample_size: int) -> List[Chunk]:
        """Get a random sample of chunks that have embeddings."""
        try:
            all_chunks = await self.contracts_text_repo.get_all_chunks()
            
            # Filter chunks with embeddings
            chunks_with_embeddings = [
                chunk for chunk in all_chunks 
                if chunk.embedding and len(chunk.embedding) > 0
            ]
            
            # Return random sample
            import random
            
            if len(chunks_with_embeddings) <= sample_size:
                return chunks_with_embeddings
            
            return random.sample(chunks_with_embeddings, sample_size)
            
        except Exception as e:
            logger.error(f"Failed to get random chunks with embeddings: {e}")
            return []
    
    async def _process_embedding_batch(self, 
                                     chunks: List[Chunk],
                                     embedding_model: str) -> Dict[str, int]:
        """Process a batch of chunks to generate embeddings."""
        batch_result = {
            "processed": 0,
            "embeddings_generated": 0,
            "errors": 0
        }
        
        try:
            # Split into smaller batches for embedding generation
            for i in range(0, len(chunks), self.embedding_batch_size):
                embedding_batch = chunks[i:i + self.embedding_batch_size]
                
                try:
                    # Extract text for embedding
                    texts = [chunk.text for chunk in embedding_batch]
                    
                    # Generate embeddings
                    embeddings = await self.aoai_client.generate_embeddings(
                        texts=texts,
                        model=embedding_model
                    )
                    
                    # Assign embeddings to chunks
                    for chunk, embedding in zip(embedding_batch, embeddings):
                        if embedding:
                            chunk.set_embedding(embedding, embedding_model)
                            batch_result["embeddings_generated"] += 1
                        
                        batch_result["processed"] += 1
                    
                    # Save updated chunks to repository
                    for chunk in embedding_batch:
                        if chunk.embedding:
                            await self.contracts_text_repo.save_chunk(chunk)
                    
                except Exception as e:
                    logger.error(f"Failed to process embedding batch: {e}")
                    batch_result["errors"] += len(embedding_batch)
                    batch_result["processed"] += len(embedding_batch)
            
            return batch_result
            
        except Exception as e:
            logger.error(f"Failed to process embedding batch: {e}")
            batch_result["errors"] = len(chunks)
            batch_result["processed"] = len(chunks)
            return batch_result
    
    async def get_embedding_statistics(self) -> Dict[str, Any]:
        """Get comprehensive statistics about embeddings."""
        try:
            # Get all chunks
            all_chunks = await self.contracts_text_repo.get_all_chunks()
            
            if not all_chunks:
                return {
                    "total_chunks": 0,
                    "chunks_with_embeddings": 0,
                    "embedding_coverage": 0,
                    "models_used": [],
                    "timestamp": datetime.utcnow().isoformat()
                }
            
            # Analyze embeddings
            chunks_with_embeddings = 0
            model_counts = {}
            dimension_stats = {}
            
            for chunk in all_chunks:
                if chunk.embedding and len(chunk.embedding) > 0:
                    chunks_with_embeddings += 1
                    
                    # Track model usage
                    model = chunk.embedding_model or "unknown"
                    model_counts[model] = model_counts.get(model, 0) + 1
                    
                    # Track dimensions
                    dim = len(chunk.embedding)
                    dimension_stats[dim] = dimension_stats.get(dim, 0) + 1
            
            coverage = chunks_with_embeddings / len(all_chunks) if all_chunks else 0
            
            stats = {
                "total_chunks": len(all_chunks),
                "chunks_with_embeddings": chunks_with_embeddings,
                "chunks_without_embeddings": len(all_chunks) - chunks_with_embeddings,
                "embedding_coverage": coverage,
                "coverage_percentage": coverage * 100,
                "models_used": list(model_counts.keys()),
                "model_distribution": model_counts,
                "dimension_distribution": dimension_stats,
                "timestamp": datetime.utcnow().isoformat()
            }
            
            return stats
            
        except Exception as e:
            logger.error(f"Failed to get embedding statistics: {e}")
            return {"error": str(e)}
