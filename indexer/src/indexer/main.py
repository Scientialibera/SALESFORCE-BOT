"""Main FastAPI application for the SharePoint document indexer."""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Dict, List, Optional, Set, Any
import uvicorn

from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config.settings import Settings
from .clients.aoai_client import AzureOpenAIClient
from .clients.cosmos_client import CosmosClient
from .clients.document_intelligence_client import DocumentIntelligenceClient
from .clients.sharepoint_client import SharePointClient
from .clients.gremlin_client import GremlinClient
from .repositories.processed_files_repository import ProcessedFilesRepository
from .repositories.contracts_text_repository import ContractsTextRepository
from .services.sharepoint_service import SharePointService
from .services.document_extraction_service import DocumentExtractionService
from .services.chunking_service import ChunkingService
from .services.vector_store_service import VectorStoreService
from .services.progress_service import ProgressService
from .services.cdc_service import CDCService
from .pipelines.contracts_pipeline import ContractsPipeline
from .pipelines.embedding_pipeline import EmbeddingPipeline
from .models.job import JobType, JobStatus


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Global application state
app_state = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan management."""
    try:
        logger.info("Initializing SharePoint Document Indexer")
        
        # Load settings
        settings = Settings()
        app_state["settings"] = settings
        
        # Initialize clients
        logger.info("Initializing Azure clients")
        
        aoai_client = AzureOpenAIClient(settings)
        cosmos_client = CosmosClient(settings)
        doc_intel_client = DocumentIntelligenceClient(settings)
        sharepoint_client = SharePointClient(settings)
        gremlin_client = GremlinClient(settings)
        
        await aoai_client.initialize()
        await cosmos_client.initialize()
        await doc_intel_client.initialize()
        await sharepoint_client.initialize()
        await gremlin_client.initialize()
        
        app_state["aoai_client"] = aoai_client
        app_state["cosmos_client"] = cosmos_client
        app_state["doc_intel_client"] = doc_intel_client
        app_state["sharepoint_client"] = sharepoint_client
        app_state["gremlin_client"] = gremlin_client
        
        # Initialize repositories
        logger.info("Initializing repositories")
        
        processed_files_repo = ProcessedFilesRepository(cosmos_client)
        contracts_text_repo = ContractsTextRepository(cosmos_client)
        
        await processed_files_repo.initialize()
        await contracts_text_repo.initialize()
        
        app_state["processed_files_repo"] = processed_files_repo
        app_state["contracts_text_repo"] = contracts_text_repo
        
        # Initialize services
        logger.info("Initializing services")
        
        sharepoint_service = SharePointService(settings, sharepoint_client)
        extraction_service = DocumentExtractionService(settings, doc_intel_client, aoai_client)
        chunking_service = ChunkingService(settings, aoai_client)
        vector_store_service = VectorStoreService(settings, aoai_client)
        progress_service = ProgressService(settings, cosmos_client)
        cdc_service = CDCService(settings, sharepoint_client, cosmos_client, processed_files_repo)
        
        await sharepoint_service.initialize()
        await extraction_service.initialize()
        await chunking_service.initialize()
        await vector_store_service.initialize()
        await progress_service.initialize()
        await cdc_service.initialize()
        
        app_state["sharepoint_service"] = sharepoint_service
        app_state["extraction_service"] = extraction_service
        app_state["chunking_service"] = chunking_service
        app_state["vector_store_service"] = vector_store_service
        app_state["progress_service"] = progress_service
        app_state["cdc_service"] = cdc_service
        
        # Initialize pipelines
        logger.info("Initializing processing pipelines")
        
        contracts_pipeline = ContractsPipeline(
            settings=settings,
            sharepoint_service=sharepoint_service,
            extraction_service=extraction_service,
            chunking_service=chunking_service,
            vector_store_service=vector_store_service,
            progress_service=progress_service,
            cdc_service=cdc_service,
            processed_files_repo=processed_files_repo,
            contracts_text_repo=contracts_text_repo
        )
        
        embedding_pipeline = EmbeddingPipeline(
            settings=settings,
            vector_store_service=vector_store_service,
            progress_service=progress_service,
            contracts_text_repo=contracts_text_repo,
            aoai_client=aoai_client
        )
        
        app_state["contracts_pipeline"] = contracts_pipeline
        app_state["embedding_pipeline"] = embedding_pipeline
        
        logger.info("SharePoint Document Indexer initialized successfully")
        
        yield
        
    except Exception as e:
        logger.error(f"Failed to initialize application: {e}")
        raise
    
    finally:
        # Cleanup
        logger.info("Shutting down SharePoint Document Indexer")
        
        # Close clients
        for client_name in ["aoai_client", "cosmos_client", "doc_intel_client", "sharepoint_client", "gremlin_client"]:
            client = app_state.get(client_name)
            if client and hasattr(client, "close"):
                try:
                    await client.close()
                except Exception as e:
                    logger.warning(f"Error closing {client_name}: {e}")
        
        # Close services
        for service_name in ["vector_store_service"]:
            service = app_state.get(service_name)
            if service and hasattr(service, "close"):
                try:
                    await service.close()
                except Exception as e:
                    logger.warning(f"Error closing {service_name}: {e}")
        
        logger.info("Shutdown complete")


# Create FastAPI application
app = FastAPI(
    title="SharePoint Document Indexer",
    description="AI-powered document indexing service for SharePoint files",
    version="1.0.0",
    lifespan=lifespan
)


# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Dependency injection
def get_contracts_pipeline() -> ContractsPipeline:
    """Get contracts pipeline dependency."""
    return app_state["contracts_pipeline"]


def get_embedding_pipeline() -> EmbeddingPipeline:
    """Get embedding pipeline dependency."""
    return app_state["embedding_pipeline"]


def get_progress_service() -> ProgressService:
    """Get progress service dependency."""
    return app_state["progress_service"]


def get_cdc_service() -> CDCService:
    """Get CDC service dependency."""
    return app_state["cdc_service"]


def get_vector_store_service() -> VectorStoreService:
    """Get vector store service dependency.""" 
    return app_state["vector_store_service"]


# Health check endpoints
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "sharepoint-document-indexer"}


@app.get("/health/detailed")
async def detailed_health_check():
    """Detailed health check with component status."""
    try:
        # Test vector store connection
        vector_store = app_state.get("vector_store_service")
        vector_store_healthy = await vector_store.test_connection() if vector_store else False
        
        # Get system metrics
        progress_service = app_state.get("progress_service")
        system_metrics = await progress_service.get_system_metrics() if progress_service else {}
        
        health_status = {
            "status": "healthy",
            "components": {
                "vector_store": "healthy" if vector_store_healthy else "unhealthy",
                "progress_service": "healthy" if progress_service else "unhealthy"
            },
            "system_metrics": system_metrics,
            "timestamp": "2024-01-01T00:00:00Z"  # Will be updated with actual timestamp
        }
        
        # Overall status
        all_healthy = all(status == "healthy" for status in health_status["components"].values())
        health_status["status"] = "healthy" if all_healthy else "degraded"
        
        return health_status
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(
            status_code=500,
            content={"status": "unhealthy", "error": str(e)}
        )


# Job management endpoints
@app.post("/jobs/full-index")
async def start_full_indexing(
    background_tasks: BackgroundTasks,
    account_filter: Optional[List[str]] = Query(None, description="Filter by account IDs"),
    force_reprocess: bool = Query(False, description="Force reprocessing of existing documents"),
    contracts_pipeline: ContractsPipeline = Depends(get_contracts_pipeline)
):
    """Start a full indexing job for all SharePoint documents."""
    try:
        account_set = set(account_filter) if account_filter else None
        
        # Run indexing in background
        background_tasks.add_task(
            contracts_pipeline.run_full_indexing,
            account_filter=account_set,
            force_reprocess=force_reprocess
        )
        
        return {
            "message": "Full indexing job started",
            "job_type": "full_index",
            "parameters": {
                "account_filter": account_filter,
                "force_reprocess": force_reprocess
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to start full indexing: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/jobs/incremental-index")
async def start_incremental_indexing(
    background_tasks: BackgroundTasks,
    account_filter: Optional[List[str]] = Query(None, description="Filter by account IDs"),
    contracts_pipeline: ContractsPipeline = Depends(get_contracts_pipeline)
):
    """Start an incremental indexing job based on document changes."""
    try:
        account_set = set(account_filter) if account_filter else None
        
        # Run indexing in background
        background_tasks.add_task(
            contracts_pipeline.run_incremental_indexing,
            account_filter=account_set
        )
        
        return {
            "message": "Incremental indexing job started",
            "job_type": "incremental_index",
            "parameters": {
                "account_filter": account_filter
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to start incremental indexing: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/jobs/regenerate-embeddings")
async def regenerate_embeddings(
    background_tasks: BackgroundTasks,
    embedding_model: Optional[str] = Query(None, description="Embedding model to use"),
    account_filter: Optional[List[str]] = Query(None, description="Filter by account IDs"),
    embedding_pipeline: EmbeddingPipeline = Depends(get_embedding_pipeline)
):
    """Regenerate embeddings for all chunks."""
    try:
        account_set = set(account_filter) if account_filter else None
        
        # Run embedding generation in background
        background_tasks.add_task(
            embedding_pipeline.regenerate_all_embeddings,
            embedding_model=embedding_model,
            account_filter=account_set
        )
        
        return {
            "message": "Embedding regeneration job started",
            "job_type": "embedding_generation",
            "parameters": {
                "embedding_model": embedding_model,
                "account_filter": account_filter
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to start embedding regeneration: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/jobs/update-missing-embeddings")
async def update_missing_embeddings(
    background_tasks: BackgroundTasks,
    embedding_model: Optional[str] = Query(None, description="Embedding model to use"),
    account_filter: Optional[List[str]] = Query(None, description="Filter by account IDs"),
    embedding_pipeline: EmbeddingPipeline = Depends(get_embedding_pipeline)
):
    """Generate embeddings for chunks that don't have them."""
    try:
        account_set = set(account_filter) if account_filter else None
        
        # Run missing embeddings generation in background
        background_tasks.add_task(
            embedding_pipeline.update_missing_embeddings,
            embedding_model=embedding_model,
            account_filter=account_set
        )
        
        return {
            "message": "Missing embeddings generation job started",
            "job_type": "missing_embeddings",
            "parameters": {
                "embedding_model": embedding_model,
                "account_filter": account_filter
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to start missing embeddings generation: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Job status endpoints
@app.get("/jobs")
async def list_jobs(
    status: Optional[str] = Query(None, description="Filter by job status"),
    job_type: Optional[str] = Query(None, description="Filter by job type"),
    limit: int = Query(100, description="Maximum number of jobs to return"),
    progress_service: ProgressService = Depends(get_progress_service)
):
    """List jobs with optional filtering."""
    try:
        job_status = JobStatus(status) if status else None
        job_type_enum = JobType(job_type) if job_type else None
        
        jobs = await progress_service.list_jobs(
            status=job_status,
            job_type=job_type_enum,
            limit=limit
        )
        
        return {
            "jobs": [
                {
                    "job_id": job.job_id,
                    "job_type": job.job_type.value,
                    "status": job.status.value,
                    "description": job.description,
                    "progress_percentage": job.progress_percentage,
                    "current_step": job.current_step,
                    "created_at": job.created_at.isoformat() if job.created_at else None,
                    "started_at": job.started_at.isoformat() if job.started_at else None,
                    "completed_at": job.completed_at.isoformat() if job.completed_at else None,
                    "error_message": job.error_message
                }
                for job in jobs
            ],
            "total": len(jobs)
        }
        
    except Exception as e:
        logger.error(f"Failed to list jobs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/jobs/{job_id}")
async def get_job_details(
    job_id: str,
    progress_service: ProgressService = Depends(get_progress_service)
):
    """Get detailed information about a specific job."""
    try:
        job = await progress_service.get_job(job_id)
        
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        
        metrics = await progress_service.get_job_metrics(job_id)
        
        return {
            "job": {
                "job_id": job.job_id,
                "job_type": job.job_type.value,
                "status": job.status.value,
                "description": job.description,
                "progress_percentage": job.progress_percentage,
                "current_step": job.current_step,
                "created_at": job.created_at.isoformat() if job.created_at else None,
                "started_at": job.started_at.isoformat() if job.started_at else None,
                "completed_at": job.completed_at.isoformat() if job.completed_at else None,
                "updated_at": job.updated_at.isoformat() if job.updated_at else None,
                "error_message": job.error_message,
                "metadata": job.metadata,
                "result": job.result.to_dict() if job.result else None
            },
            "metrics": metrics
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get job details: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/jobs/{job_id}")
async def cancel_job(
    job_id: str,
    reason: Optional[str] = Query(None, description="Cancellation reason"),
    progress_service: ProgressService = Depends(get_progress_service)
):
    """Cancel a running or pending job."""
    try:
        success = await progress_service.cancel_job(job_id, reason)
        
        if not success:
            raise HTTPException(status_code=400, detail="Job could not be cancelled")
        
        return {"message": f"Job {job_id} cancelled successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to cancel job: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Change Data Capture endpoints
@app.post("/cdc/scan")
async def scan_for_changes(
    background_tasks: BackgroundTasks,
    account_filter: Optional[List[str]] = Query(None, description="Filter by account IDs"),
    cdc_service: CDCService = Depends(get_cdc_service)
):
    """Scan SharePoint for document changes."""
    try:
        account_set = set(account_filter) if account_filter else None
        
        # Run CDC scan in background
        background_tasks.add_task(
            cdc_service.scan_for_changes,
            account_filter=account_set
        )
        
        return {
            "message": "CDC scan started",
            "parameters": {
                "account_filter": account_filter
            }
        }
        
    except Exception as e:
        logger.error(f"Failed to start CDC scan: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/cdc/statistics")
async def get_cdc_statistics(
    hours_back: int = Query(24, description="Hours to look back for statistics"),
    cdc_service: CDCService = Depends(get_cdc_service)
):
    """Get CDC statistics."""
    try:
        stats = await cdc_service.get_change_statistics(hours_back)
        return stats
        
    except Exception as e:
        logger.error(f"Failed to get CDC statistics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Search endpoints
@app.get("/search")
async def search_documents(
    query: str = Query(..., description="Search query"),
    account_id: Optional[str] = Query(None, description="Filter by account ID"),
    top_k: int = Query(10, description="Number of results to return"),
    score_threshold: float = Query(0.7, description="Minimum similarity score"),
    search_type: str = Query("hybrid", description="Search type: 'semantic', 'hybrid'"),
    vector_store_service: VectorStoreService = Depends(get_vector_store_service)
):
    """Search for documents using vector similarity."""
    try:
        if search_type == "semantic":
            results = await vector_store_service.search_similar_chunks(
                query_text=query,
                account_id=account_id,
                top_k=top_k,
                score_threshold=score_threshold
            )
        elif search_type == "hybrid":
            results = await vector_store_service.hybrid_search(
                query_text=query,
                account_id=account_id,
                top_k=top_k
            )
        else:
            raise HTTPException(status_code=400, detail="Invalid search type. Use 'semantic' or 'hybrid'")
        
        return {
            "query": query,
            "search_type": search_type,
            "results": results,
            "total_results": len(results)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Statistics endpoints
@app.get("/statistics/system")
async def get_system_statistics(
    progress_service: ProgressService = Depends(get_progress_service)
):
    """Get system-wide statistics."""
    try:
        stats = await progress_service.get_system_metrics()
        return stats
        
    except Exception as e:
        logger.error(f"Failed to get system statistics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/statistics/pipeline")
async def get_pipeline_statistics(
    contracts_pipeline: ContractsPipeline = Depends(get_contracts_pipeline)
):
    """Get pipeline status and statistics."""
    try:
        status = await contracts_pipeline.get_pipeline_status()
        return status
        
    except Exception as e:
        logger.error(f"Failed to get pipeline statistics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/statistics/embeddings")
async def get_embedding_statistics(
    embedding_pipeline: EmbeddingPipeline = Depends(get_embedding_pipeline)
):
    """Get embedding statistics."""
    try:
        stats = await embedding_pipeline.get_embedding_statistics()
        return stats
        
    except Exception as e:
        logger.error(f"Failed to get embedding statistics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# Main entry point
if __name__ == "__main__":
    uvicorn.run(
        "indexer.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,  # Set to True for development
        log_level="info"
    )
