"""
Telemetry service for comprehensive application monitoring and observability.

This service handles metrics collection, performance tracking, usage analytics,
and integration with Azure Application Insights and custom telemetry systems.
"""

from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta
from enum import Enum
import json
import structlog
import asyncio
from dataclasses import dataclass, asdict

from azure.monitor.opentelemetry import configure_azure_monitor
from opentelemetry import trace, metrics
from opentelemetry.trace import Status, StatusCode
from opentelemetry.metrics import get_meter

from chatbot.models.rbac import RBACContext
from chatbot.clients.cosmos_client import CosmosClient

logger = structlog.get_logger(__name__)


class EventType(Enum):
    """Types of telemetry events."""
    USER_INTERACTION = "user_interaction"
    AGENT_EXECUTION = "agent_execution"
    PLAN_CREATION = "plan_creation"
    PLAN_EXECUTION = "plan_execution"
    TOOL_INVOCATION = "tool_invocation"
    QUERY_EXECUTION = "query_execution"
    ERROR_OCCURRED = "error_occurred"
    PERFORMANCE_METRIC = "performance_metric"
    SECURITY_EVENT = "security_event"
    FEEDBACK_RECEIVED = "feedback_received"


class Severity(Enum):
    """Event severity levels."""
    CRITICAL = "critical"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    DEBUG = "debug"


@dataclass
class TelemetryEvent:
    """Structured telemetry event."""
    event_id: str
    event_type: EventType
    timestamp: datetime
    user_id: Optional[str]
    tenant_id: Optional[str]
    session_id: Optional[str]
    severity: Severity
    message: str
    properties: Dict[str, Any]
    metrics: Dict[str, float]
    duration_ms: Optional[float] = None
    success: Optional[bool] = None
    error_details: Optional[Dict[str, Any]] = None


class TelemetryService:
    """Service for comprehensive application telemetry and monitoring."""
    
    def __init__(
        self,
        cosmos_client: CosmosClient,
        app_insights_connection_string: Optional[str] = None,
        enable_detailed_tracking: bool = True
    ):
        """
        Initialize the telemetry service.
        
        Args:
            cosmos_client: Cosmos DB client for telemetry storage
            app_insights_connection_string: Application Insights connection string
            enable_detailed_tracking: Whether to enable detailed performance tracking
        """
        self.cosmos_client = cosmos_client
        self.enable_detailed_tracking = enable_detailed_tracking
        
        # Initialize OpenTelemetry
        if app_insights_connection_string:
            configure_azure_monitor(connection_string=app_insights_connection_string)
        
        self.tracer = trace.get_tracer(__name__)
        self.meter = get_meter(__name__)
        
        # Initialize metrics
        self._init_metrics()
        
        # Telemetry storage
        self.telemetry_database = "telemetry"
        self.events_container = "events"
        self.metrics_container = "metrics"
        self.performance_container = "performance"
        
        # Performance tracking
        self.active_spans = {}
        self.performance_cache = {}
    
    def _init_metrics(self):
        """Initialize OpenTelemetry metrics."""
        # Counters
        self.request_counter = self.meter.create_counter(
            "chatbot_requests_total",
            description="Total number of requests processed"
        )
        
        self.error_counter = self.meter.create_counter(
            "chatbot_errors_total",
            description="Total number of errors encountered"
        )
        
        # Histograms
        self.response_time_histogram = self.meter.create_histogram(
            "chatbot_response_time_seconds",
            description="Response time in seconds"
        )
        
        self.token_usage_histogram = self.meter.create_histogram(
            "chatbot_token_usage",
            description="Token usage per request"
        )
        
        # Gauges (via up-down counter)
        self.active_sessions_gauge = self.meter.create_up_down_counter(
            "chatbot_active_sessions",
            description="Number of active chat sessions"
        )
    
    async def track_event(
        self,
        event_type: EventType,
        message: str,
        rbac_context: Optional[RBACContext] = None,
        session_id: Optional[str] = None,
        severity: Severity = Severity.INFO,
        properties: Optional[Dict[str, Any]] = None,
        metrics: Optional[Dict[str, float]] = None,
        duration_ms: Optional[float] = None,
        success: Optional[bool] = None,
        error_details: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Track a telemetry event.
        
        Args:
            event_type: Type of event
            message: Event message
            rbac_context: Optional user context
            session_id: Optional session identifier
            severity: Event severity
            properties: Optional custom properties
            metrics: Optional custom metrics
            duration_ms: Optional duration in milliseconds
            success: Optional success indicator
            error_details: Optional error details
            
        Returns:
            Event ID
        """
        try:
            from uuid import uuid4
            
            event = TelemetryEvent(
                event_id=str(uuid4()),
                event_type=event_type,
                timestamp=datetime.utcnow(),
                user_id=rbac_context.user_id if rbac_context else None,
                tenant_id=rbac_context.tenant_id if rbac_context else None,
                session_id=session_id,
                severity=severity,
                message=message,
                properties=properties or {},
                metrics=metrics or {},
                duration_ms=duration_ms,
                success=success,
                error_details=error_details
            )
            
            # Update OpenTelemetry metrics
            self._update_metrics(event)
            
            # Store event asynchronously
            asyncio.create_task(self._store_event(event))
            
            # Log structured event
            logger.info(
                "Telemetry event tracked",
                event_id=event.event_id,
                event_type=event_type.value,
                severity=severity.value,
                user_id=event.user_id,
                session_id=session_id
            )
            
            return event.event_id
            
        except Exception as e:
            logger.error("Failed to track telemetry event", error=str(e))
            raise
    
    async def start_performance_tracking(
        self,
        operation_name: str,
        rbac_context: Optional[RBACContext] = None,
        properties: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Start performance tracking for an operation.
        
        Args:
            operation_name: Name of the operation
            rbac_context: Optional user context
            properties: Optional operation properties
            
        Returns:
            Tracking ID
        """
        try:
            from uuid import uuid4
            
            tracking_id = str(uuid4())
            
            # Start OpenTelemetry span
            span = self.tracer.start_span(operation_name)
            
            if rbac_context:
                span.set_attribute("user.id", rbac_context.user_id)
                span.set_attribute("tenant.id", rbac_context.tenant_id)
            
            if properties:
                for key, value in properties.items():
                    span.set_attribute(f"operation.{key}", str(value))
            
            # Store tracking info
            self.active_spans[tracking_id] = {
                "span": span,
                "start_time": datetime.utcnow(),
                "operation_name": operation_name,
                "rbac_context": rbac_context,
                "properties": properties or {}
            }
            
            logger.debug(
                "Performance tracking started",
                tracking_id=tracking_id,
                operation_name=operation_name
            )
            
            return tracking_id
            
        except Exception as e:
            logger.error("Failed to start performance tracking", error=str(e))
            raise
    
    async def end_performance_tracking(
        self,
        tracking_id: str,
        success: bool = True,
        error_details: Optional[Dict[str, Any]] = None,
        metrics: Optional[Dict[str, float]] = None
    ) -> Optional[float]:
        """
        End performance tracking for an operation.
        
        Args:
            tracking_id: Tracking ID from start_performance_tracking
            success: Whether the operation succeeded
            error_details: Optional error details
            metrics: Optional custom metrics
            
        Returns:
            Duration in milliseconds
        """
        try:
            if tracking_id not in self.active_spans:
                logger.warning("Tracking ID not found", tracking_id=tracking_id)
                return None
            
            tracking_info = self.active_spans.pop(tracking_id)
            span = tracking_info["span"]
            start_time = tracking_info["start_time"]
            
            # Calculate duration
            end_time = datetime.utcnow()
            duration_ms = (end_time - start_time).total_seconds() * 1000
            
            # Update span
            span.set_attribute("duration.ms", duration_ms)
            span.set_attribute("success", success)
            
            if not success:
                span.set_status(Status(StatusCode.ERROR))
                if error_details:
                    span.set_attribute("error.details", json.dumps(error_details))
            else:
                span.set_status(Status(StatusCode.OK))
            
            if metrics:
                for key, value in metrics.items():
                    span.set_attribute(f"metric.{key}", value)
            
            # End span
            span.end()
            
            # Record metrics
            self.response_time_histogram.record(
                duration_ms / 1000,  # Convert to seconds
                attributes={"operation": tracking_info["operation_name"]}
            )
            
            # Track performance event
            await self.track_event(
                EventType.PERFORMANCE_METRIC,
                f"Operation {tracking_info['operation_name']} completed",
                rbac_context=tracking_info["rbac_context"],
                severity=Severity.INFO,
                properties={
                    "operation_name": tracking_info["operation_name"],
                    **tracking_info["properties"]
                },
                metrics={
                    "duration_ms": duration_ms,
                    **(metrics or {})
                },
                duration_ms=duration_ms,
                success=success,
                error_details=error_details
            )
            
            logger.debug(
                "Performance tracking ended",
                tracking_id=tracking_id,
                duration_ms=duration_ms,
                success=success
            )
            
            return duration_ms
            
        except Exception as e:
            logger.error("Failed to end performance tracking", error=str(e))
            return None
    
    async def track_user_interaction(
        self,
        interaction_type: str,
        rbac_context: RBACContext,
        session_id: str,
        details: Dict[str, Any]
    ):
        """
        Track user interaction events.
        
        Args:
            interaction_type: Type of interaction (chat, search, etc.)
            rbac_context: User's RBAC context
            session_id: Session identifier
            details: Interaction details
        """
        await self.track_event(
            EventType.USER_INTERACTION,
            f"User interaction: {interaction_type}",
            rbac_context=rbac_context,
            session_id=session_id,
            properties={
                "interaction_type": interaction_type,
                **details
            }
        )
        
        # Update metrics
        self.request_counter.add(
            1,
            attributes={
                "interaction_type": interaction_type,
                "tenant_id": rbac_context.tenant_id
            }
        )
    
    async def track_agent_execution(
        self,
        agent_name: str,
        plan_id: str,
        rbac_context: RBACContext,
        execution_details: Dict[str, Any],
        duration_ms: float,
        success: bool
    ):
        """
        Track agent execution events.
        
        Args:
            agent_name: Name of the agent
            plan_id: Plan identifier
            rbac_context: User's RBAC context
            execution_details: Execution details
            duration_ms: Execution duration
            success: Whether execution succeeded
        """
        await self.track_event(
            EventType.AGENT_EXECUTION,
            f"Agent {agent_name} execution",
            rbac_context=rbac_context,
            properties={
                "agent_name": agent_name,
                "plan_id": plan_id,
                **execution_details
            },
            metrics={"duration_ms": duration_ms},
            duration_ms=duration_ms,
            success=success
        )
    
    async def track_security_event(
        self,
        event_description: str,
        rbac_context: Optional[RBACContext] = None,
        severity: Severity = Severity.WARNING,
        security_details: Optional[Dict[str, Any]] = None
    ):
        """
        Track security-related events.
        
        Args:
            event_description: Description of the security event
            rbac_context: Optional user context
            severity: Event severity
            security_details: Optional security details
        """
        await self.track_event(
            EventType.SECURITY_EVENT,
            event_description,
            rbac_context=rbac_context,
            severity=severity,
            properties=security_details or {}
        )
        
        # Also log as security event
        logger.warning(
            "Security event detected",
            event_description=event_description,
            user_id=rbac_context.user_id if rbac_context else None,
            details=security_details
        )
    
    async def get_usage_analytics(
        self,
        tenant_id: str,
        start_date: datetime,
        end_date: datetime,
        metric_types: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Get usage analytics for a tenant.
        
        Args:
            tenant_id: Tenant identifier
            start_date: Start date for analytics
            end_date: End date for analytics
            metric_types: Optional list of metric types to include
            
        Returns:
            Usage analytics data
        """
        try:
            events_container = self.cosmos_client.get_container(
                self.telemetry_database, self.events_container
            )
            
            # Build query
            query = """
                SELECT 
                    c.event_type,
                    c.severity,
                    c.timestamp,
                    c.properties,
                    c.metrics,
                    c.success
                FROM c 
                WHERE c.tenant_id = @tenant_id
                AND c.timestamp >= @start_date
                AND c.timestamp <= @end_date
            """
            
            parameters = [
                {"name": "@tenant_id", "value": tenant_id},
                {"name": "@start_date", "value": start_date.isoformat()},
                {"name": "@end_date", "value": end_date.isoformat()}
            ]
            
            if metric_types:
                placeholders = ", ".join([f"@type{i}" for i in range(len(metric_types))])
                query += f" AND c.event_type IN ({placeholders})"
                parameters.extend([
                    {"name": f"@type{i}", "value": metric_type}
                    for i, metric_type in enumerate(metric_types)
                ])
            
            # Execute query
            events = []
            async for event in events_container.query_items(
                query=query,
                parameters=parameters,
                enable_cross_partition_query=True
            ):
                events.append(event)
            
            # Analyze events
            analytics = self._analyze_events(events, start_date, end_date)
            
            logger.info(
                "Usage analytics generated",
                tenant_id=tenant_id,
                events_analyzed=len(events),
                date_range=f"{start_date.date()} to {end_date.date()}"
            )
            
            return analytics
            
        except Exception as e:
            logger.error(
                "Failed to get usage analytics",
                tenant_id=tenant_id,
                error=str(e)
            )
            raise
    
    async def _store_event(self, event: TelemetryEvent):
        """
        Store telemetry event in Cosmos DB.
        
        Args:
            event: Telemetry event to store
        """
        try:
            events_container = self.cosmos_client.get_container(
                self.telemetry_database, self.events_container
            )
            
            # Convert event to dict
            event_data = asdict(event)
            event_data["event_type"] = event.event_type.value
            event_data["severity"] = event.severity.value
            event_data["timestamp"] = event.timestamp.isoformat()
            
            # Add partition key
            event_data["id"] = event.event_id
            event_data["pk"] = event.tenant_id or "global"
            
            await events_container.create_item(event_data)
            
        except Exception as e:
            logger.error("Failed to store telemetry event", error=str(e))
    
    def _update_metrics(self, event: TelemetryEvent):
        """
        Update OpenTelemetry metrics based on event.
        
        Args:
            event: Telemetry event
        """
        try:
            # Update counters
            if event.severity in [Severity.ERROR, Severity.CRITICAL]:
                self.error_counter.add(
                    1,
                    attributes={
                        "event_type": event.event_type.value,
                        "severity": event.severity.value
                    }
                )
            
            # Update custom metrics
            for metric_name, metric_value in event.metrics.items():
                if metric_name == "token_usage":
                    self.token_usage_histogram.record(
                        metric_value,
                        attributes={"event_type": event.event_type.value}
                    )
                elif metric_name == "duration_ms" and event.duration_ms:
                    self.response_time_histogram.record(
                        event.duration_ms / 1000,  # Convert to seconds
                        attributes={"event_type": event.event_type.value}
                    )
            
        except Exception as e:
            logger.warning("Failed to update metrics", error=str(e))
    
    def _analyze_events(
        self,
        events: List[Dict[str, Any]],
        start_date: datetime,
        end_date: datetime
    ) -> Dict[str, Any]:
        """
        Analyze events to generate usage analytics.
        
        Args:
            events: List of events
            start_date: Analysis start date
            end_date: Analysis end date
            
        Returns:
            Analytics data
        """
        # Initialize analytics
        analytics = {
            "period": {
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "days": (end_date - start_date).days
            },
            "summary": {
                "total_events": len(events),
                "unique_users": len(set(e.get("user_id") for e in events if e.get("user_id"))),
                "unique_sessions": len(set(e.get("session_id") for e in events if e.get("session_id")))
            },
            "event_types": {},
            "daily_usage": {},
            "performance": {
                "avg_response_time_ms": 0,
                "total_tokens_used": 0,
                "success_rate": 0
            },
            "errors": []
        }
        
        # Analyze by event type
        event_type_counts = {}
        total_duration = 0
        duration_count = 0
        total_tokens = 0
        success_count = 0
        total_with_success = 0
        
        for event in events:
            event_type = event.get("event_type", "unknown")
            event_type_counts[event_type] = event_type_counts.get(event_type, 0) + 1
            
            # Performance metrics
            if event.get("duration_ms"):
                total_duration += event["duration_ms"]
                duration_count += 1
            
            if event.get("metrics", {}).get("token_usage"):
                total_tokens += event["metrics"]["token_usage"]
            
            if event.get("success") is not None:
                total_with_success += 1
                if event["success"]:
                    success_count += 1
            
            # Collect errors
            if event.get("severity") in ["error", "critical"]:
                analytics["errors"].append({
                    "timestamp": event.get("timestamp"),
                    "event_type": event_type,
                    "message": event.get("message", ""),
                    "error_details": event.get("error_details")
                })
        
        # Calculate performance metrics
        if duration_count > 0:
            analytics["performance"]["avg_response_time_ms"] = total_duration / duration_count
        
        analytics["performance"]["total_tokens_used"] = total_tokens
        
        if total_with_success > 0:
            analytics["performance"]["success_rate"] = success_count / total_with_success
        
        analytics["event_types"] = event_type_counts
        
        return analytics
