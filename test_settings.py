#!/usr/bin/env python3
"""Test script to check settings values."""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'chatbot', 'src'))

from chatbot.config.settings import settings

print(f"Dev mode: {settings.dev_mode}")
print(f"Environment: {settings.environment}")
print(f"Debug: {settings.debug}")
print(f"App name: {settings.app_name}")