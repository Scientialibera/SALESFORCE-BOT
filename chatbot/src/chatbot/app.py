"""
FastAPI application factory and configuration.

This module creates and configures the FastAPI application with all
necessary middleware, routes, and dependencies.
"""

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Dict, Any
import structlog
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
import uvicorn
import uuid

# Import settings and dependencies
from chatbot.config.settings import settings

# Import clients
from chatbot.clients.aoai_client import AzureOpenAIClient
from chatbot.clients.cosmos_client import CosmosDBClient
from chatbot.clients.gremlin_client import GremlinClient
from chatbot.clients.fabric_client import FabricLakehouseClient

# Import repositories
# Chat/history/cache/feedback repositories removed - unified service uses Cosmos client directly
from chatbot.repositories.agent_functions_repository import AgentFunctionsRepository
from chatbot.repositories.prompts_repository import PromptsRepository
from chatbot.repositories.sql_schema_repository import SQLSchemaRepository

# Import services
from chatbot.services.rbac_service import RBACService
from chatbot.services.account_resolver_service import AccountResolverService
from chatbot.services.sql_service import SQLService
from chatbot.services.graph_service import GraphService
from chatbot.services.retrieval_service import RetrievalService
from chatbot.services.telemetry_service import TelemetryService

# Import agents
from chatbot.agents.sql_agent import SQLAgent
from chatbot.agents.graph_agent import GraphAgent

# Import utilities
from chatbot.utils.embeddings import EmbeddingUtils

# Import routes
from chatbot.routes.chat import router as chat_router

# Configure structured logging
structlog.configure(
    processors=[
        structlog.dev.ConsoleRenderer() if settings.debug else structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(
        min_level=getattr(logging, settings.telemetry.log_level.upper(), logging.INFO)
    ),
    logger_factory=structlog.WriteLoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger(__name__)


class ApplicationState:
    """Application state container for shared resources."""
    
    def __init__(self):
        # Clients
        self.aoai_client: AzureOpenAIClient = None
        self.cosmos_client: CosmosDBClient = None
        self.gremlin_client: GremlinClient = None
        self.fabric_client: FabricLakehouseClient = None
        
        # Repositories
        self.agent_functions_repository = None
        self.prompts_repository = None
        self.sql_schema_repository = None

        # Services
        self.rbac_service = None
        self.account_resolver_service = None
        self.sql_service = None
        self.graph_service = None
        self.retrieval_service = None
        self.telemetry_service = None
        self.planner_service = None

        # Unified data service (replaces cache, history, feedback services)
        self.unified_data_service = None

        # Agents
        self.sql_agent = None
        self.graph_agent = None


# Global application state
app_state = ApplicationState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager for startup and shutdown.
    
    This handles initialization and cleanup of shared resources
    like database connections and Azure service clients.
    """
    # Startup
    logger.info("Starting Account Q&A Bot application", version=settings.version)
    
    try:
        # Initialize Azure clients
        logger.info("Initializing Azure service clients")
        app_state.aoai_client = AzureOpenAIClient(settings.azure_openai)
        logger.info("Azure OpenAI client initialized successfully")
        
        app_state.cosmos_client = CosmosDBClient(settings.cosmos_db)
        logger.info("Cosmos DB client initialized successfully")
        
        # Initialize Gremlin client only if an endpoint is configured. This
        # allows local development and tests to run without a Gremlin server.
        if getattr(settings.gremlin, "endpoint", None):
            app_state.gremlin_client = GremlinClient(settings.gremlin)
            logger.info("Gremlin client initialized successfully")
        else:
            app_state.gremlin_client = None
            logger.info("Gremlin endpoint not configured; skipping Gremlin client initialization")
        
        app_state.fabric_client = FabricLakehouseClient(
            settings.fabric_lakehouse.sql_endpoint,
            settings.fabric_lakehouse.database,
            settings.fabric_lakehouse.workspace_id,
            settings.fabric_lakehouse.connection_timeout,
            dev_mode=settings.dev_mode
        )
        logger.info("Fabric client initialized successfully")
        
        # Initialize repositories
        logger.info("Initializing data repositories")
        app_state.agent_functions_repository = AgentFunctionsRepository(
            app_state.cosmos_client,
            settings.cosmos_db.database_name,
            settings.cosmos_db.agent_functions_container,
        )
        app_state.prompts_repository = PromptsRepository(
            app_state.cosmos_client,
            settings.cosmos_db.database_name,
            settings.cosmos_db.prompts_container,
        )
        app_state.sql_schema_repository = SQLSchemaRepository(
            app_state.cosmos_client,
            settings.cosmos_db.database_name,
            settings.cosmos_db.sql_schema_container,
        )
        logger.info("Repositories initialized successfully")
        
        # Initialize services
        logger.info("Initializing application services")

        # Initialize RBAC service with settings. In dev_mode, disable enforcement to bypass RBAC for testing.
        rbac_settings = settings.rbac
        if settings.dev_mode:
            # Create a shallow copy-like override to ensure enforcement is disabled in dev
            try:
                # Pydantic BaseSettings is immutable by default - create a new RBACSettings instance
                from chatbot.config.settings import RBACSettings
                rbac_settings = RBACSettings(**{**rbac_settings.model_dump(), "enforce_rbac": False})
            except Exception:
                # Fallback: set attribute if possible
                try:
                    setattr(rbac_settings, "enforce_rbac", False)
                except Exception:
                    pass

        app_state.rbac_service = RBACService(rbac_settings)
        logger.info("Initialized RBAC service", enforce_rbac=rbac_settings.enforce_rbac, admin_users=len(rbac_settings.admin_users or []))

        # Compose a unified facade that exposes cache/history/feedback APIs and
        # colocates data in the chat container. We keep the original
        # per-service attributes for backwards compatibility, but also set
        # `unified_data_service` for convenience.
        from chatbot.services.unified_service import UnifiedDataService
        unified = UnifiedDataService(app_state.cosmos_client, settings.cosmos_db)
        # assign the unified service to app state
        app_state.unified_data_service = unified

        app_state.telemetry_service = TelemetryService(
            app_state.cosmos_client,
            enable_detailed_tracking=settings.debug
        )

        # Initialize planner service
        from chatbot.services.planner_service import PlannerService
        app_state.planner_service = PlannerService(
            app_state.agent_functions_repository,
            app_state.prompts_repository,
            app_state.rbac_service,
            app_state.aoai_client
        )

        # Initialize account resolver service using unified service for cache ops
        app_state.account_resolver_service = AccountResolverService(
            app_state.aoai_client,
            app_state.unified_data_service,
            confidence_threshold=settings.account_resolver.confidence_threshold,
            max_suggestions=settings.account_resolver.max_candidates,
        )
        logger.info("Account resolver service initialized", confidence_threshold=settings.account_resolver.confidence_threshold)

        app_state.sql_service = SQLService(
            app_state.aoai_client,
            app_state.sql_schema_repository,
            app_state.unified_data_service,
            app_state.telemetry_service,
            settings.fabric_lakehouse,
            dev_mode=settings.dev_mode
        )

        # Legacy services replaced by unified_data_service

        app_state.graph_service = GraphService(
            app_state.gremlin_client,
            dev_mode=settings.dev_mode
        )

        # Initialize embedding utils
        from chatbot.utils.embeddings import EmbeddingUtils
        embedding_utils = EmbeddingUtils()

        app_state.retrieval_service = RetrievalService(
            app_state.aoai_client,
            app_state.cosmos_client,
            app_state.unified_data_service,
            embedding_utils
        )
        
        # Initialize agents
        logger.info("Initializing simplified agents")

        # Initialize SQL agent
        app_state.sql_agent = SQLAgent(
            app_state.sql_service,
            app_state.account_resolver_service,
            app_state.telemetry_service,
        )

        # Initialize Graph agent
        app_state.graph_agent = GraphAgent(
            app_state.graph_service,
            app_state.telemetry_service,
        )

        logger.info("Agents initialized")
        logger.info("SQL agent enabled" if settings.agents.sql_agent_enabled else "SQL agent disabled")
        logger.info("Graph agent enabled" if settings.agents.graph_agent_enabled else "Graph agent disabled")
        
        logger.info("Application startup completed successfully")
        
        # This is where we yield control to the FastAPI application
        yield
        
    except Exception as e:
        logger.error("Failed to start application", error=str(e))
        raise
    
    finally:
        # Shutdown
        logger.info("Shutting down application")
        
        try:
            # Close clients
            if app_state.aoai_client:
                await app_state.aoai_client.close()
                logger.info("Azure OpenAI client closed")
            if app_state.cosmos_client:
                await app_state.cosmos_client.close()
                logger.info("Cosmos DB client closed")
            if app_state.gremlin_client:
                await app_state.gremlin_client.close()
                logger.info("Gremlin client closed")
            if app_state.fabric_client:
                await app_state.fabric_client.close()
                logger.info("Fabric lakehouse client closed")
            
            logger.info("Application shutdown completed")
            
        except Exception as e:
            logger.error("Error during application shutdown", error=str(e))


def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.
    
    Returns:
        Configured FastAPI application instance
    """
    # Create FastAPI app with lifespan management
    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        description="Account Q&A Bot with Azure services",
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        openapi_url="/openapi.json" if settings.debug else None,
        lifespan=lifespan,
    )
    
    # Add middleware
    configure_middleware(app)
    
    # Add routes
    configure_routes(app)
    
    # Add exception handlers
    configure_exception_handlers(app)
    
    logger.info(
        "Created FastAPI application",
        app_name=settings.app_name,
        version=settings.version,
        debug=settings.debug,
    )
    
    return app


def configure_middleware(app: FastAPI) -> None:
    """Configure application middleware."""
    
    # CORS middleware
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["*"],
        )
        logger.info("Configured CORS middleware", origins=settings.cors_origins)
    
    # Trusted host middleware for security
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["*"] if settings.debug else ["localhost", "127.0.0.1"],
    )
    
    # Request logging middleware
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        """Log HTTP requests and responses with comprehensive debugging."""
        import asyncio
        import traceback
        
        start_time = asyncio.get_event_loop().time()
        request_id = str(uuid.uuid4())[:8]
        
        # Log request start
        logger.info(
            "HTTP request started",
            request_id=request_id,
            method=request.method,
            url=str(request.url),
            user_agent=request.headers.get("user-agent"),
        )
        
        print(f"DEBUG: [{request_id}] REQUEST START: {request.method} {request.url}")
        print(f"DEBUG: [{request_id}] Headers: {dict(request.headers)}")
        
        # Debug event loop state before processing
        loop = asyncio.get_event_loop()
        tasks_before = asyncio.all_tasks(loop)
        print(f"DEBUG: [{request_id}] Tasks before request: {len(tasks_before)}")
        print(f"DEBUG: [{request_id}] Event loop running: {loop.is_running()}, closed: {loop.is_closed()}")
        
        # Process request
        try:
            print(f"DEBUG: [{request_id}] About to call next middleware/handler")
            response = await call_next(request)
            duration = asyncio.get_event_loop().time() - start_time
            
            print(f"DEBUG: [{request_id}] Handler completed successfully")
            print(f"DEBUG: [{request_id}] Response status: {response.status_code}")
            
            # Debug event loop state after processing
            tasks_after = asyncio.all_tasks(loop)
            print(f"DEBUG: [{request_id}] Tasks after request: {len(tasks_after)}")
            print(f"DEBUG: [{request_id}] Event loop running: {loop.is_running()}, closed: {loop.is_closed()}")
            
            # Log response
            logger.info(
                "HTTP request completed",
                request_id=request_id,
                method=request.method,
                url=str(request.url),
                status_code=response.status_code,
                duration_ms=int(duration * 1000),
            )
            
            print(f"DEBUG: [{request_id}] REQUEST COMPLETED successfully")
            return response
            
        except Exception as e:
            duration = asyncio.get_event_loop().time() - start_time
            
            print(f"DEBUG: [{request_id}] EXCEPTION in request processing:")
            print(f"DEBUG: [{request_id}] Exception type: {type(e).__name__}")
            print(f"DEBUG: [{request_id}] Exception message: {str(e)}")
            print(f"DEBUG: [{request_id}] Traceback:\n{traceback.format_exc()}")
            
            # Debug event loop state after exception
            tasks_after = asyncio.all_tasks(loop)
            print(f"DEBUG: [{request_id}] Tasks after exception: {len(tasks_after)}")
            print(f"DEBUG: [{request_id}] Event loop running: {loop.is_running()}, closed: {loop.is_closed()}")
            
            logger.error(
                "HTTP request failed",
                request_id=request_id,
                method=request.method,
                url=str(request.url),
                error=str(e),
                duration_ms=int(duration * 1000),
                traceback=traceback.format_exc(),
            )
            
            print(f"DEBUG: [{request_id}] About to re-raise exception")
            raise
            
            return response
            
        except Exception as e:
            duration = asyncio.get_event_loop().time() - start_time
            
            logger.error(
                "HTTP request failed",
                method=request.method,
                url=str(request.url),
                error=str(e),
                duration_ms=int(duration * 1000),
            )
            raise


def configure_routes(app: FastAPI) -> None:
    """Configure application routes."""
    # Chat API routes (auth required)
    app.include_router(
        chat_router,
        prefix=settings.api_prefix,
        tags=["chat"],
    )

    logger.info("Configured application routes", api_prefix=settings.api_prefix)


def configure_exception_handlers(app: FastAPI) -> None:
    """Configure global exception handlers."""
    
    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        """Handle HTTP exceptions with structured logging."""
        logger.warning(
            "HTTP exception",
            status_code=exc.status_code,
            detail=exc.detail,
            url=str(request.url),
        )
        
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.status_code,
                    "message": exc.detail,
                    "type": "http_exception",
                }
            },
        )
    
    @app.exception_handler(Exception)
    async def general_exception_handler(request: Request, exc: Exception):
        """Handle unexpected exceptions with structured logging."""
        import traceback
        
        logger.error(
            "Unhandled exception",
            error=str(exc),
            error_type=type(exc).__name__,
            url=str(request.url),
            traceback=traceback.format_exc(),
        )
        
        # Print to console for debugging
        print(f"UNHANDLED EXCEPTION: {type(exc).__name__}: {str(exc)}")
        print(f"Traceback:\n{traceback.format_exc()}")
        
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": 500,
                    "message": "Internal server error" if not settings.debug else str(exc),
                    "type": "internal_error",
                    "traceback": traceback.format_exc() if settings.debug else None,
                }
            },
        )


# Dependency injection functions for clients
def get_aoai_client() -> AzureOpenAIClient:
    """Get Azure OpenAI client dependency."""
    if not app_state.aoai_client:
        raise HTTPException(status_code=503, detail="Azure OpenAI client not available")
    return app_state.aoai_client


def get_cosmos_client() -> CosmosDBClient:
    """Get Cosmos DB client dependency."""
    if not app_state.cosmos_client:
        raise HTTPException(status_code=503, detail="Cosmos DB client not available")
    return app_state.cosmos_client


def get_gremlin_client() -> GremlinClient:
    """Get Gremlin client dependency."""
    if not app_state.gremlin_client:
        raise HTTPException(status_code=503, detail="Gremlin client not available")
    return app_state.gremlin_client


def get_fabric_client() -> FabricLakehouseClient:
    """Get Fabric Lakehouse client dependency."""
    if not app_state.fabric_client:
        raise HTTPException(status_code=503, detail="Fabric Lakehouse client not available")
    return app_state.fabric_client


# Dependency injection functions for repositories
def get_agent_functions_repository() -> AgentFunctionsRepository:
    """Get agent functions repository dependency."""
    if not app_state.agent_functions_repository:
        raise HTTPException(status_code=503, detail="Agent functions repository not available")
    return app_state.agent_functions_repository


def get_prompts_repository() -> PromptsRepository:
    """Get prompts repository dependency."""
    if not app_state.prompts_repository:
        raise HTTPException(status_code=503, detail="Prompts repository not available")
    return app_state.prompts_repository


def get_sql_schema_repository() -> SQLSchemaRepository:
    """Get SQL schema repository dependency."""
    if not app_state.sql_schema_repository:
        raise HTTPException(status_code=503, detail="SQL schema repository not available")
    return app_state.sql_schema_repository


# Dependency injection functions for services
def get_rbac_service() -> RBACService:
    """Get RBAC service dependency."""
    if not app_state.rbac_service:
        raise HTTPException(status_code=503, detail="RBAC service not available")
    return app_state.rbac_service


def get_account_resolver_service() -> AccountResolverService:
    """Get account resolver service dependency."""
    if not app_state.account_resolver_service:
        raise HTTPException(status_code=503, detail="Account resolver service not available")
    return app_state.account_resolver_service


def get_sql_service() -> SQLService:
    """Get SQL service dependency."""
    if not app_state.sql_service:
        raise HTTPException(status_code=503, detail="SQL service not available")
    return app_state.sql_service


def get_graph_service() -> GraphService:
    """Get graph service dependency."""
    if not app_state.graph_service:
        raise HTTPException(status_code=503, detail="Graph service not available")
    return app_state.graph_service


def get_retrieval_service() -> RetrievalService:
    """Get retrieval service dependency."""
    if not app_state.retrieval_service:
        raise HTTPException(status_code=503, detail="Retrieval service not available")
    return app_state.retrieval_service


def get_telemetry_service() -> TelemetryService:
    """Get telemetry service dependency."""
    if not app_state.telemetry_service:
        raise HTTPException(status_code=503, detail="Telemetry service not available")
    return app_state.telemetry_service


def get_unified_data_service():
    """Get unified data service dependency (replaces cache, history, feedback services)."""
    uds = getattr(app_state, "unified_data_service", None)
    if not uds:
        raise HTTPException(status_code=503, detail="Unified data service not available")
    return uds


def get_planner_service():
    """Get planner service dependency."""
    if not app_state.planner_service:
        raise HTTPException(status_code=503, detail="Planner service not available")
    return app_state.planner_service


# Dependency injection functions for agents
def get_sql_agent() -> SQLAgent:
    """Get SQL agent dependency."""
    if not app_state.sql_agent:
        raise HTTPException(status_code=503, detail="SQL agent not available")
    return app_state.sql_agent


def get_graph_agent() -> GraphAgent:
    """Get graph agent dependency."""
    if not app_state.graph_agent:
        raise HTTPException(status_code=503, detail="Graph agent not available")
    return app_state.graph_agent


# Create the application instance
app = create_app()


if __name__ == "__main__":
    # Run the application directly (for development)
    uvicorn.run(
        "chatbot.app:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug,
        log_level=settings.telemetry.log_level.lower(),
    )
