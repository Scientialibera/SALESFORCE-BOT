"""
Minimal version of the main app to test startup without Azure dependencies.
"""
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import structlog

logger = structlog.get_logger(__name__)

@asynccontextmanager
async def minimal_lifespan(app: FastAPI):
    """Minimal lifespan that just yields without any Azure initialization."""
    logger.info("Starting minimal app")
    print("DEBUG: Minimal lifespan starting...")
    
    # Just yield without any initialization
    print("DEBUG: About to yield")
    yield
    
    print("DEBUG: Lifespan shutting down")
    logger.info("Minimal app shutting down")

# Create minimal app
app = FastAPI(
    title="Minimal Salesforce Bot",
    version="1.0.0",
    description="Minimal version for testing",
    lifespan=minimal_lifespan
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "Minimal app is running", "status": "ok"}

@app.post("/api/chat")
async def chat_endpoint():
    return {"response": "This is a minimal response", "status": "ok"}

@app.get("/api/health")
async def health_check():
    return {"status": "healthy", "message": "Minimal app is running"}