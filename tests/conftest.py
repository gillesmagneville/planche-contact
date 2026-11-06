# -*- coding: utf-8 -*-
"""Allows `import portfolio` from the tests without installing the package:
adds the repository root (parent of tests/) to sys.path, as
portfolio/portfolio.py already does for the CLI."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


import pytest


@pytest.fixture(autouse=True)
def _english_by_default():
    """The language of portfolio.i18n is a global of the process (set by the
    CLI's main(), by set_language()...): each test starts in English, the
    fallback language, whatever an earlier test or the language of the machine
    running the tests. A test that checks another language sets it itself."""
    from portfolio.i18n import get_language, set_language

    previous = get_language()
    set_language("en")
    yield
    set_language(previous)
