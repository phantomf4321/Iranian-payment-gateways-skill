import httpx
import pytest


@pytest.fixture(autouse=True)
def prohibit_real_gateway_http(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Routine tests must use an httpx.MockTransport")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", blocked)
