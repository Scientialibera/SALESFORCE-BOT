"""Job model for tracking pipeline runs."""

from datetime import datetime, timedelta
from enum import Enum
from typing import Dict, List, Optional, Any
from uuid import uuid4
from pydantic import BaseModel, Field, ConfigDict


class JobType(str, Enum):
    """Types of indexing jobs."""
    FULL_SYNC = "full_sync"
    INCREMENTAL = "incremental"
    SINGLE_DOCUMENT = "single_document"
    REINDEX = "reindex"
    CLEANUP = "cleanup"


class JobStatus(str, Enum):
    """Job execution status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    PAUSED = "paused"


class JobMetrics(BaseModel):
    """Metrics for job execution."""
    model_config = ConfigDict(extra="allow")
    
    # Document processing counts
    documents_found: int = 0
    documents_processed: int = 0
    documents_failed: int = 0
    documents_skipped: int = 0
    
    # Chunk processing counts
    chunks_created: int = 0
    chunks_indexed: int = 0
    chunks_failed: int = 0
    
    # Vector processing counts
    embeddings_generated: int = 0
    embeddings_failed: int = 0
    
    # Graph processing counts
    vertices_created: int = 0
    edges_created: int = 0
    graph_operations_failed: int = 0
    
    # Performance metrics
    avg_processing_time_ms: Optional[float] = None
    total_size_mb: Optional[float] = None
    throughput_docs_per_min: Optional[float] = None
    
    # Error tracking
    error_count: int = 0
    warning_count: int = 0


class JobError(BaseModel):
    """Individual job error details."""
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    error_type: str
    error_message: str
    document_id: Optional[str] = None
    file_path: Optional[str] = None
    stack_trace: Optional[str] = None
    retry_count: int = 0


class JobConfiguration(BaseModel):
    """Job configuration parameters."""
    model_config = ConfigDict(extra="allow")
    
    # Source configuration
    sharepoint_sites: List[str] = Field(default_factory=list)
    file_extensions: List[str] = Field(default_factory=lambda: [".pdf", ".docx", ".txt", ".md"])
    max_file_size_mb: int = 100
    
    # Processing configuration
    chunk_size: int = 1000
    chunk_overlap: int = 200
    embedding_model: str = "text-embedding-3-small"
    
    # Retry configuration
    max_retries: int = 3
    retry_delay_seconds: int = 30
    
    # Parallel processing
    max_concurrent_documents: int = 5
    max_concurrent_chunks: int = 10
    
    # Feature flags
    enable_ocr: bool = True
    enable_entity_extraction: bool = True
    enable_graph_indexing: bool = True
    enable_vector_indexing: bool = True


class Job(BaseModel):
    """Represents a document indexing job run."""
    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        str_strip_whitespace=True
    )
    
    # Primary identifiers
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    job_type: JobType
    
    # Status and timing
    status: JobStatus = JobStatus.PENDING
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    last_heartbeat: Optional[datetime] = None
    
    # Configuration
    configuration: JobConfiguration = Field(default_factory=JobConfiguration)
    
    # Progress tracking
    metrics: JobMetrics = Field(default_factory=JobMetrics)
    current_phase: Optional[str] = None
    progress_percentage: float = Field(default=0.0, ge=0.0, le=100.0)
    
    # Error handling
    errors: List[JobError] = Field(default_factory=list)
    last_error: Optional[str] = None
    
    # Execution context
    worker_id: Optional[str] = None
    priority: int = Field(default=5, ge=1, le=10)  # 1=highest, 10=lowest
    
    # Result tracking
    result_summary: Optional[Dict[str, Any]] = None
    log_file_path: Optional[str] = None
    
    @property
    def duration(self) -> Optional[timedelta]:
        """Get job execution duration."""
        if not self.started_at:
            return None
        end_time = self.completed_at or datetime.utcnow()
        return end_time - self.started_at
    
    @property
    def is_running(self) -> bool:
        """Check if job is currently running."""
        return self.status == JobStatus.RUNNING
    
    @property
    def is_completed(self) -> bool:
        """Check if job is completed (success or failure)."""
        return self.status in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]
    
    @property
    def success_rate(self) -> float:
        """Calculate success rate for processed documents."""
        total = self.metrics.documents_processed + self.metrics.documents_failed
        if total == 0:
            return 0.0
        return (self.metrics.documents_processed / total) * 100
    
    def start(self, worker_id: str = None) -> None:
        """Mark job as started."""
        self.status = JobStatus.RUNNING
        self.started_at = datetime.utcnow()
        self.last_heartbeat = datetime.utcnow()
        if worker_id:
            self.worker_id = worker_id
    
    def complete(self, result_summary: Dict[str, Any] = None) -> None:
        """Mark job as completed successfully."""
        self.status = JobStatus.COMPLETED
        self.completed_at = datetime.utcnow()
        self.progress_percentage = 100.0
        if result_summary:
            self.result_summary = result_summary
    
    def fail(self, error_message: str, error_type: str = "JobExecutionError") -> None:
        """Mark job as failed."""
        self.status = JobStatus.FAILED
        self.completed_at = datetime.utcnow()
        self.last_error = error_message
        
        # Add error to error list
        error = JobError(
            error_type=error_type,
            error_message=error_message
        )
        self.errors.append(error)
        self.metrics.error_count += 1
    
    def cancel(self) -> None:
        """Cancel the job."""
        self.status = JobStatus.CANCELLED
        self.completed_at = datetime.utcnow()
    
    def pause(self) -> None:
        """Pause the job."""
        self.status = JobStatus.PAUSED
    
    def resume(self) -> None:
        """Resume a paused job."""
        if self.status == JobStatus.PAUSED:
            self.status = JobStatus.RUNNING
            self.last_heartbeat = datetime.utcnow()
    
    def update_heartbeat(self) -> None:
        """Update last heartbeat timestamp."""
        self.last_heartbeat = datetime.utcnow()
    
    def update_progress(self, phase: str, percentage: float) -> None:
        """Update job progress."""
        self.current_phase = phase
        self.progress_percentage = max(0.0, min(100.0, percentage))
        self.update_heartbeat()
    
    def add_error(self, error_message: str, error_type: str = "ProcessingError", 
                  document_id: str = None, file_path: str = None, 
                  stack_trace: str = None) -> None:
        """Add an error to the job."""
        error = JobError(
            error_type=error_type,
            error_message=error_message,
            document_id=document_id,
            file_path=file_path,
            stack_trace=stack_trace
        )
        self.errors.append(error)
        self.metrics.error_count += 1
        self.last_error = error_message
    
    def increment_metric(self, metric_name: str, value: int = 1) -> None:
        """Increment a metric counter."""
        if hasattr(self.metrics, metric_name):
            current_value = getattr(self.metrics, metric_name)
            setattr(self.metrics, metric_name, current_value + value)
    
    def calculate_throughput(self) -> None:
        """Calculate processing throughput."""
        if self.duration and self.duration.total_seconds() > 0:
            docs_per_second = self.metrics.documents_processed / self.duration.total_seconds()
            self.metrics.throughput_docs_per_min = docs_per_second * 60
    
    def get_status_summary(self) -> Dict[str, Any]:
        """Get a summary of job status."""
        return {
            "id": self.id,
            "name": self.name,
            "type": self.job_type,
            "status": self.status,
            "progress": f"{self.progress_percentage:.1f}%",
            "phase": self.current_phase,
            "duration": str(self.duration) if self.duration else None,
            "documents_processed": self.metrics.documents_processed,
            "documents_failed": self.metrics.documents_failed,
            "chunks_created": self.metrics.chunks_created,
            "error_count": self.metrics.error_count,
            "success_rate": f"{self.success_rate:.1f}%",
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None
        }
    
    @classmethod
    def create_full_sync_job(cls, name: str, sharepoint_sites: List[str], 
                            config: JobConfiguration = None) -> "Job":
        """Create a full synchronization job."""
        if config is None:
            config = JobConfiguration()
        config.sharepoint_sites = sharepoint_sites
        
        return cls(
            name=name,
            job_type=JobType.FULL_SYNC,
            configuration=config,
            priority=3  # Higher priority for full syncs
        )
    
    @classmethod
    def create_incremental_job(cls, name: str, sharepoint_sites: List[str],
                              config: JobConfiguration = None) -> "Job":
        """Create an incremental synchronization job."""
        if config is None:
            config = JobConfiguration()
        config.sharepoint_sites = sharepoint_sites
        
        return cls(
            name=name,
            job_type=JobType.INCREMENTAL,
            configuration=config,
            priority=5  # Normal priority for incremental
        )
    
    @classmethod
    def create_single_document_job(cls, name: str, document_path: str,
                                  config: JobConfiguration = None) -> "Job":
        """Create a single document processing job."""
        if config is None:
            config = JobConfiguration()
        
        return cls(
            name=name,
            job_type=JobType.SINGLE_DOCUMENT,
            configuration=config,
            priority=1  # Highest priority for single docs
        )
