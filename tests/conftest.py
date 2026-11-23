"""No network in ordinary in-process tests; subprocess checks use offline fixtures."""

import socket

import pytest


def pytest_sessionfinish(session, exitstatus):
    reporter = session.config.pluginmanager.getplugin("terminalreporter")
    if reporter and any(reporter.stats.get(kind) for kind in ("skipped", "xfailed", "xpassed")):
        session.exitstatus = 1


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Network is disabled in the default test suite")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket.socket, "sendto", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)
