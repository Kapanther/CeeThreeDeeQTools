from pathlib import Path

import pytest


@pytest.fixture
def minimal_landxml_path() -> Path:
    return Path(__file__).parent / "fixtures" / "landxml_minimal.xml"
