"""
Test FastAPI app with minimal lifespan to isolate the shutdown issue.
"""
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
import structlog

logger = structlog.get_logger(__name__)

@asynccontextmanager
async def simple_lifespan(app: FastAPI):
    """Minimal lifespan function for testing."""
    print("DEBUG: Simple lifespan starting...")
    logger.info("Simple test app starting")
    
    print("DEBUG: About to yield - server should stay running")
    yield
    
    print("DEBUG: Simple lifespan shutting down")
    logger.info("Simple test app shutting down")

# Create test app
test_app = FastAPI(
    title="Test App",
    version="1.0.0",
    lifespan=simple_lifespan
)

@test_app.get("/")
async def root():
    return {"message": "Test app is running"}

@test_app.get("/api/test")
async def test_endpoint():
    return {"status": "ok", "message": "Test endpoint working"}