import os
import sys

# Make `src` importable when running `python -m pytest tests/` from project root.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
