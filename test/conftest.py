"""Shared fixtures and helpers for all unit tests."""
import pytest


@pytest.fixture(autouse=True)
def reset_dev_plan():
    """Reset the global dev_plan singleton between every test."""
    from src.agents.coding.pending import dev_plan
    dev_plan.clear()
    yield
    dev_plan.clear()


@pytest.fixture(autouse=True)
def reset_pending_changes():
    """Reset the global pending_changes singleton between every test."""
    from src.agents.coding.pending import pending_changes
    pending_changes.clear()
    yield
    pending_changes.clear()


@pytest.fixture(autouse=True)
def reset_session_cache():
    """Reset the module-level session_cache between every test."""
    from src.infra.tools_cache import session_cache
    session_cache.clear()
    yield
    session_cache.clear()
