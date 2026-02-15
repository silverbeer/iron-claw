"""Shared fixtures and CLI options for iron-claw RADIUS integration tests."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from pyrad.client import Client
from pyrad.dictionary import Dictionary

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def pytest_addoption(parser):
    parser.addoption(
        "--radius-server",
        default=os.environ.get("RADIUS_SERVER", "localhost"),
        help="RADIUS server address (default: $RADIUS_SERVER or localhost)",
    )
    parser.addoption(
        "--radius-secret",
        default=os.environ.get("RADIUS_SECRET", "testing123"),
        help="RADIUS shared secret (default: $RADIUS_SECRET or testing123)",
    )
    parser.addoption(
        "--radius-auth-port",
        type=int,
        default=int(os.environ.get("RADIUS_AUTH_PORT", "1812")),
        help="RADIUS auth port (default: $RADIUS_AUTH_PORT or 1812)",
    )
    parser.addoption(
        "--radius-acct-port",
        type=int,
        default=int(os.environ.get("RADIUS_ACCT_PORT", "1813")),
        help="RADIUS accounting port (default: $RADIUS_ACCT_PORT or 1813)",
    )


@pytest.fixture(scope="session")
def radius_dictionary():
    """Load the bundled RADIUS dictionary with MissTable VSAs."""
    dict_path = Path(__file__).parent.parent / "src" / "radius" / "dictionary"
    return Dictionary(str(dict_path))


@pytest.fixture(scope="session")
def radius_client(request, radius_dictionary):
    """Create a pyrad Client configured for the target RADIUS server."""
    server = request.config.getoption("--radius-server")
    secret = request.config.getoption("--radius-secret")
    auth_port = request.config.getoption("--radius-auth-port")
    acct_port = request.config.getoption("--radius-acct-port")

    client = Client(
        server=server,
        secret=secret.encode(),
        dict=radius_dictionary,
        authport=auth_port,
        acctport=acct_port,
    )
    client.retries = 3
    client.timeout = 10
    return client
