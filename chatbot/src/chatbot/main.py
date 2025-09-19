"""
Main entry point for the Account Q&A Bot application.

This module serves as the primary entry point for the FastAPI application,
providing the ASGI application instance for deployment.
"""

import sys
import os
from pathlib import Path

# Add the src directory to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from chatbot.app import app

# Export the app instance for ASGI servers
__all__ = ["app"]
