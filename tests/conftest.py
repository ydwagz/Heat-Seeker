"""Make the app's modules importable from the tests: `core.*`, `main` and `translations`
live in Application/."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "Application"))
