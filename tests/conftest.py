# -*- coding: utf-8 -*-
"""Permet `import portfolio` depuis les tests sans installation du paquet."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
