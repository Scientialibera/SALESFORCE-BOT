#!/usr/bin/env python3
"""
Startup script for the Salesforce chatbot FastAPI application.
"""

import sys
import os
import uvicorn
from dotenv import load_dotenv

# Load .env file
load_dotenv()

# Add the src directory to Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
src_dir = os.path.join(current_dir, 'src')
sys.path.insert(0, src_dir)

if __name__ == "__main__":
    # Run uvicorn with the import string for better reload support
    uvicorn.run(
        "chatbot.main:app",
        host="0.0.0.0", 
        port=8000, 
        reload=True,
        reload_dirs=[src_dir]
    )