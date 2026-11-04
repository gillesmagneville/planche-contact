# -*- coding: utf-8 -*-
"""Allows `import portfolio` from the tests without installing the package:
adds the repository root (parent of tests/) to sys.path, as
portfolio/portfolio.py already does for the CLI."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
