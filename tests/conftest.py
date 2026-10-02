# -*- coding: utf-8 -*-
"""Permet `import portfolio` depuis les tests sans installation du paquet :
ajoute la racine du dépôt (parent de tests/) au sys.path, comme le fait
déjà portfolio/portfolio.py pour le CLI."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
