"""Shared fixtures. Every test that touches the store must use `local_store`,
otherwise `load_rule` would read the developer's `data/origin.json` and an
approved draft leftover from a manual demo would fail the YAML-identity tests.
"""

import pytest


@pytest.fixture
def local_store(tmp_path, monkeypatch):
    from origin import store

    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "DB_PATH", tmp_path / "origin.json")
    return store
