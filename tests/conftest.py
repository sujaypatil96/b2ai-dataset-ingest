from pathlib import Path

import pytest

DATA_DIR = Path(__file__).parent / "data"


@pytest.fixture
def multisession_dir() -> Path:
    """Path to the hand-crafted multi-session fixture (see tests/data/multisession)."""
    return DATA_DIR / "multisession"
