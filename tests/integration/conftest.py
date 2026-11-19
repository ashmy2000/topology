import pytest

from kg.load_pdi import load


@pytest.fixture(scope='session')
def graph():
    """The graph model rebuilt once from out/pdi/; returns relationships created per type."""
    return load()
