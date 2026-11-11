import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(ROOT))


@pytest.fixture
def catalog_bytes() -> bytes:
    return (FIXTURES / "sample_catalog.html").read_bytes()


@pytest.fixture
def transcript_bytes() -> bytes:
    return (FIXTURES / "transcript.html").read_bytes()
