#!/usr/bin/env python3
"""
WAMA Dev AI - Quick runner script

Run from PyCharm or terminal:
    python wama-dev-ai/run.py

Or make it executable and run directly:
    chmod +x wama-dev-ai/run.py
    ./wama-dev-ai/run.py

Debug mode:
    python wama-dev-ai/run.py --debug
"""

import sys
import os
from pathlib import Path
import logging

# IMPORTANT: Bypass proxy for localhost BEFORE any other imports
# This must be set before requests/httpx/ollama libraries are loaded
os.environ['NO_PROXY'] = 'localhost,127.0.0.1,::1'
os.environ['no_proxy'] = 'localhost,127.0.0.1,::1'

# Setup logging based on --debug flag
if '--debug' in sys.argv:
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        datefmt='%H:%M:%S'
    )
    sys.argv.remove('--debug')
else:
    logging.basicConfig(level=logging.WARNING)

# Get the wama-dev-ai directory and its parent
SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_DIR = SCRIPT_DIR.parent.resolve()

# Add wama-dev-ai to path for imports within the package
sys.path.insert(0, str(SCRIPT_DIR))

# Change to project directory
os.chdir(PROJECT_DIR)

# Now import - using direct imports since we added SCRIPT_DIR to path
from cli import main

if __name__ == "__main__":
    main()
