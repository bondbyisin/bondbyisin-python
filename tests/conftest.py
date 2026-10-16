"""All unit tests run offline and ignore credentials from the host environment."""

import pytest


@pytest.fixture(autouse=True)
def no_credentials(monkeypatch):
    monkeypatch.delenv("BOND_API_KEY", raising=False)
    monkeypatch.delenv("BONDBYISIN_API_KEY", raising=False)
    monkeypatch.setattr("bondbyisin.client.time.sleep", lambda _: None)
