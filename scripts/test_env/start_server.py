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
# Go up to scripts, then to project root, then into chatbot/src
scripts_dir = os.path.dirname(current_dir)  # scripts
project_root = os.path.dirname(scripts_dir)  # SALESFORCE-BOT
src_dir = os.path.join(project_root, 'chatbot', 'src')
sys.path.insert(0, src_dir)

print(f"Added to path: {src_dir}")
print(f"Python path: {sys.path[:3]}")

if __name__ == "__main__":
    # Run uvicorn with the import string for better reload support
    uvicorn.run(
        "chatbot.main:app",
        host="0.0.0.0", 
        port=8000, 
        reload=True,
        reload_dirs=[src_dir]
    )