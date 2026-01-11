import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Ensure tests never depend on a developer's real OpenRouter key from .env.
os.environ.setdefault("OPENROUTER_API_KEY", "test-openrouter-api-key-1234567890")
