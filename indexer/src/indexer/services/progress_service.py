"""Service for tracking indexing progress and job status."""

import asyncio
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from enum import Enum
import uuid

from ..clients.cosmos_client import CosmosClient
from ..models.job import Job, JobStatus, JobType, JobResult
from ..config.settings import Settings


logger = logging.getLogger(__name__)


class ProgressMetric(Enum):
    """Progress metrics for tracking indexing operations."""
    DOCUMENTS_DISCOVERED = "documents_discovered"
    DOCUMENTS_PROCESSED = "documents_processed"
    CHUNKS_CREATED = "chunks_created"
    CHUNKS_INDEXED = "chunks_indexed"
    ENTITIES_EXTRACTED = "entities_extracted"
    ERRORS_ENCOUNTERED = "errors_encountered"
    BYTES_PROCESSED = "bytes_processed"


class ProgressService:
    """Service for tracking and managing indexing progress."""
    
    def __init__(self, settings: Settings, cosmos_client: CosmosClient):
        """Initialize the progress service."""
        self.settings = settings
        self.cosmos_client = cosmos_client
        self.container_name = "progress"  # Progress tracking container
        self._active_jobs: Dict[str, Job] = {}
        self._metrics_cache: Dict[str, Dict[str, Any]] = {}
    
    async def initialize(self):
        """Initialize the service."""
        try:
            # Ensure progress container exists
            await self.cosmos_client.create_container_if_not_exists(
                container_name=self.container_name,
                partition_key="/job_id"
            )
            
            # Load active jobs
            await self._load_active_jobs()
            
            logger.info("Progress service initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize progress service: {e}")
            raise
    
    async def _load_active_jobs(self):
        """Load active jobs from storage."""
        try:
            query = """
                SELECT * FROM c 
                WHERE c.type = 'job' 
                AND c.status IN ('running', 'pending')
                ORDER BY c.created_at DESC
            """
            
            items = await self.cosmos_client.query_items(
                container_name=self.container_name,
                query=query
            )
            
            for item in items:
                job = Job.from_dict(item)
                self._active_jobs[job.job_id] = job
            
            logger.info(f"Loaded {len(self._active_jobs)} active jobs")
            
        except Exception as e:
            logger.error(f"Failed to load active jobs: {e}")
    
    async def create_job(self, job_type: JobType, 
                        description: str = None,
                        metadata: Dict[str, Any] = None) -> Job:
        """Create a new indexing job."""
        try:
            job = Job(
                job_id=str(uuid.uuid4()),
                job_type=job_type,
                status=JobStatus.PENDING,
                description=description or f"{job_type.value} job",
                metadata=metadata or {},
                created_at=datetime.utcnow()
            )
            
            # Save to storage
            await self._save_job(job)
            
            # Add to active jobs
            self._active_jobs[job.job_id] = job
            
            logger.info(f"Created job {job.job_id}: {job.description}")
            
            return job
            
        except Exception as e:
            logger.error(f"Failed to create job: {e}")
            raise
    
    async def start_job(self, job_id: str) -> bool:
        """Start a pending job."""
        try:
            job = self._active_jobs.get(job_id)
            if not job:
                # Try to load from storage
                job = await self.get_job(job_id)
                if not job:
                    logger.error(f"Job {job_id} not found")
                    return False
            
            if job.status != JobStatus.PENDING:
                logger.warning(f"Job {job_id} is not in pending status: {job.status}")
                return False
            
            job.status = JobStatus.RUNNING
            job.started_at = datetime.utcnow()
            
            await self._save_job(job)
            self._active_jobs[job_id] = job
            
            logger.info(f"Started job {job_id}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to start job {job_id}: {e}")
            return False
    
    async def complete_job(self, job_id: str, 
                          result: JobResult = None,
                          error_message: str = None) -> bool:
        """Complete a running job."""
        try:
            job = self._active_jobs.get(job_id)
            if not job:
                logger.error(f"Job {job_id} not found in active jobs")
                return False
            
            if error_message:
                job.status = JobStatus.FAILED
                job.error_message = error_message
            else:
                job.status = JobStatus.COMPLETED
                job.result = result
            
            job.completed_at = datetime.utcnow()
            
            await self._save_job(job)
            
            # Remove from active jobs
            del self._active_jobs[job_id]
            
            logger.info(f"Completed job {job_id} with status {job.status}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to complete job {job_id}: {e}")
            return False
    
    async def update_job_progress(self, job_id: str, 
                                progress_percentage: float = None,
                                current_step: str = None,
                                metadata_updates: Dict[str, Any] = None) -> bool:
        """Update job progress information."""
        try:
            job = self._active_jobs.get(job_id)
            if not job:
                logger.error(f"Job {job_id} not found in active jobs")
                return False
            
            if progress_percentage is not None:
                job.progress_percentage = max(0, min(100, progress_percentage))
            
            if current_step:
                job.current_step = current_step
            
            if metadata_updates:
                job.metadata.update(metadata_updates)
            
            job.updated_at = datetime.utcnow()
            
            await self._save_job(job)
            
            logger.debug(f"Updated progress for job {job_id}: {job.progress_percentage}% - {job.current_step}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to update job progress {job_id}: {e}")
            return False
    
    async def record_metric(self, job_id: str, 
                          metric: ProgressMetric, 
                          value: int,
                          increment: bool = False) -> bool:
        """Record a progress metric for a job."""
        try:
            job = self._active_jobs.get(job_id)
            if not job:
                logger.error(f"Job {job_id} not found in active jobs")
                return False
            
            metric_key = metric.value
            
            if increment:
                current_value = job.metadata.get(metric_key, 0)
                new_value = current_value + value
            else:
                new_value = value
            
            job.metadata[metric_key] = new_value
            job.updated_at = datetime.utcnow()
            
            await self._save_job(job)
            
            logger.debug(f"Recorded metric {metric_key}={new_value} for job {job_id}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to record metric for job {job_id}: {e}")
            return False
    
    async def get_job(self, job_id: str) -> Optional[Job]:
        """Get a job by ID."""
        try:
            # Check active jobs first
            if job_id in self._active_jobs:
                return self._active_jobs[job_id]
            
            # Query storage
            item = await self.cosmos_client.get_item(
                container_name=self.container_name,
                item_id=job_id,
                partition_key=job_id
            )
            
            if item and item.get("type") == "job":
                return Job.from_dict(item)
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to get job {job_id}: {e}")
            return None
    
    async def list_jobs(self, status: JobStatus = None,
                       job_type: JobType = None,
                       limit: int = 100) -> List[Job]:
        """List jobs with optional filtering."""
        try:
            query_parts = ["SELECT * FROM c WHERE c.type = 'job'"]
            
            if status:
                query_parts.append(f"AND c.status = '{status.value}'")
            
            if job_type:
                query_parts.append(f"AND c.job_type = '{job_type.value}'")
            
            query_parts.append("ORDER BY c.created_at DESC")
            
            if limit:
                query_parts.append(f"OFFSET 0 LIMIT {limit}")
            
            query = " ".join(query_parts)
            
            items = await self.cosmos_client.query_items(
                container_name=self.container_name,
                query=query
            )
            
            return [Job.from_dict(item) for item in items]
            
        except Exception as e:
            logger.error(f"Failed to list jobs: {e}")
            return []
    
    async def get_active_jobs(self) -> List[Job]:
        """Get all currently active jobs."""
        return list(self._active_jobs.values())
    
    async def cancel_job(self, job_id: str, reason: str = None) -> bool:
        """Cancel a running or pending job."""
        try:
            job = self._active_jobs.get(job_id)
            if not job:
                logger.error(f"Job {job_id} not found in active jobs")
                return False
            
            if job.status not in [JobStatus.PENDING, JobStatus.RUNNING]:
                logger.warning(f"Job {job_id} cannot be cancelled from status {job.status}")
                return False
            
            job.status = JobStatus.CANCELLED
            job.error_message = reason or "Job was cancelled"
            job.completed_at = datetime.utcnow()
            
            await self._save_job(job)
            
            # Remove from active jobs
            del self._active_jobs[job_id]
            
            logger.info(f"Cancelled job {job_id}: {reason}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to cancel job {job_id}: {e}")
            return False
    
    async def cleanup_old_jobs(self, days_old: int = 30) -> int:
        """Clean up old completed/failed jobs."""
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days_old)
            
            query = f"""
                SELECT c.id, c.job_id FROM c 
                WHERE c.type = 'job' 
                AND c.status IN ('completed', 'failed', 'cancelled')
                AND c.completed_at < '{cutoff_date.isoformat()}'
            """
            
            items = await self.cosmos_client.query_items(
                container_name=self.container_name,
                query=query
            )
            
            deleted_count = 0
            for item in items:
                try:
                    await self.cosmos_client.delete_item(
                        container_name=self.container_name,
                        item_id=item["id"],
                        partition_key=item["job_id"]
                    )
                    deleted_count += 1
                except Exception as e:
                    logger.warning(f"Failed to delete old job {item['id']}: {e}")
            
            logger.info(f"Cleaned up {deleted_count} old jobs")
            
            return deleted_count
            
        except Exception as e:
            logger.error(f"Failed to cleanup old jobs: {e}")
            return 0
    
    async def get_job_metrics(self, job_id: str) -> Dict[str, Any]:
        """Get comprehensive metrics for a job."""
        try:
            job = await self.get_job(job_id)
            if not job:
                return {}
            
            metrics = {
                "job_id": job.job_id,
                "job_type": job.job_type.value,
                "status": job.status.value,
                "progress_percentage": job.progress_percentage,
                "current_step": job.current_step,
                "created_at": job.created_at.isoformat() if job.created_at else None,
                "started_at": job.started_at.isoformat() if job.started_at else None,
                "completed_at": job.completed_at.isoformat() if job.completed_at else None,
                "updated_at": job.updated_at.isoformat() if job.updated_at else None,
            }
            
            # Add duration if applicable
            if job.started_at:
                end_time = job.completed_at or datetime.utcnow()
                duration = end_time - job.started_at
                metrics["duration_seconds"] = duration.total_seconds()
            
            # Add metadata metrics
            for metric in ProgressMetric:
                key = metric.value
                if key in job.metadata:
                    metrics[key] = job.metadata[key]
            
            return metrics
            
        except Exception as e:
            logger.error(f"Failed to get job metrics {job_id}: {e}")
            return {}
    
    async def get_system_metrics(self) -> Dict[str, Any]:
        """Get system-wide indexing metrics."""
        try:
            # Get job statistics
            query = """
                SELECT c.status, COUNT(1) as count 
                FROM c 
                WHERE c.type = 'job' 
                GROUP BY c.status
            """
            
            status_counts = await self.cosmos_client.query_items(
                container_name=self.container_name,
                query=query
            )
            
            # Get recent activity (last 24 hours)
            recent_cutoff = datetime.utcnow() - timedelta(hours=24)
            recent_query = f"""
                SELECT COUNT(1) as count FROM c 
                WHERE c.type = 'job' 
                AND c.created_at > '{recent_cutoff.isoformat()}'
            """
            
            recent_jobs = await self.cosmos_client.query_items(
                container_name=self.container_name,
                query=recent_query
            )
            
            metrics = {
                "active_jobs": len(self._active_jobs),
                "total_jobs_24h": recent_jobs[0]["count"] if recent_jobs else 0,
                "job_status_counts": {item["status"]: item["count"] for item in status_counts},
                "timestamp": datetime.utcnow().isoformat()
            }
            
            return metrics
            
        except Exception as e:
            logger.error(f"Failed to get system metrics: {e}")
            return {}
    
    async def _save_job(self, job: Job):
        """Save job to storage."""
        try:
            job_dict = job.to_dict()
            job_dict["type"] = "job"  # Add type for queries
            
            await self.cosmos_client.upsert_item(
                container_name=self.container_name,
                item=job_dict
            )
            
        except Exception as e:
            logger.error(f"Failed to save job {job.job_id}: {e}")
            raise
