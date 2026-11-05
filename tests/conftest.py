import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(scope='session')
def day_world():
    """One world run for a simulated day, shared by read-only checks."""
    from app.world import World
    w = World(seed=7)
    w.advance(1440)
    return w
