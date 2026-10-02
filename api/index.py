"""Compatibility ASGI entry point retained for existing deployments."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.main import app as app
