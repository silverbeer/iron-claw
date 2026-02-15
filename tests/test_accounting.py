"""Accounting tests for iron-claw RADIUS (Accounting-Request -> Response)."""

from __future__ import annotations

import uuid

import pyrad.packet
import pytest


@pytest.fixture()
def session_id():
    """Generate a unique RADIUS session ID per test."""
    return uuid.uuid4().hex[:16]


def _create_acct_packet(radius_client, session_id, status_type, **extra):
    """Build an Accounting-Request with required AVPs."""
    req = radius_client.CreateAcctPacket(
        code=pyrad.packet.AccountingRequest,
    )
    req["User-Name"] = "iron-claw-scraper"
    req["Acct-Session-Id"] = session_id
    req["Acct-Status-Type"] = status_type
    req["NAS-Identifier"] = "iron-claw"
    req["NAS-IP-Address"] = "127.0.0.1"
    for key, value in extra.items():
        req[key] = value
    return req


class TestAccounting:
    """Accounting protocol tests — verify server accepts Start/Stop/Interim."""

    @pytest.mark.integration
    def test_accounting_start_accepted(self, radius_client, session_id):
        req = _create_acct_packet(radius_client, session_id, "Start")
        reply = radius_client.SendPacket(req)
        assert reply.code == pyrad.packet.AccountingResponse

    @pytest.mark.integration
    def test_accounting_stop_accepted(self, radius_client, session_id):
        start = _create_acct_packet(radius_client, session_id, "Start")
        radius_client.SendPacket(start)

        stop = _create_acct_packet(
            radius_client,
            session_id,
            "Stop",
            **{"Acct-Session-Time": 120},
        )
        reply = radius_client.SendPacket(stop)
        assert reply.code == pyrad.packet.AccountingResponse

    @pytest.mark.integration
    def test_interim_update_accepted(self, radius_client, session_id):
        start = _create_acct_packet(radius_client, session_id, "Start")
        radius_client.SendPacket(start)

        interim = _create_acct_packet(
            radius_client,
            session_id,
            "Interim-Update",
            **{"Acct-Session-Time": 60},
        )
        reply = radius_client.SendPacket(interim)
        assert reply.code == pyrad.packet.AccountingResponse

    @pytest.mark.integration
    def test_accounting_with_token_tracking(self, radius_client, session_id):
        """Verify token counts in Acct-Input-Octets are accepted."""
        start = _create_acct_packet(radius_client, session_id, "Start")
        radius_client.SendPacket(start)

        # Send interim with token count in Acct-Input-Octets
        interim = _create_acct_packet(
            radius_client,
            session_id,
            "Interim-Update",
            **{
                "Acct-Session-Time": 30,
                "Acct-Input-Octets": 15000,  # 15k tokens used
                "Acct-Output-Octets": 5,  # 5 matches found
            },
        )
        reply = radius_client.SendPacket(interim)
        assert reply.code == pyrad.packet.AccountingResponse

        # Stop with final totals
        stop = _create_acct_packet(
            radius_client,
            session_id,
            "Stop",
            **{
                "Acct-Session-Time": 90,
                "Acct-Input-Octets": 45000,  # 45k tokens total
                "Acct-Output-Octets": 12,  # 12 matches total
                "Acct-Terminate-Cause": "User-Request",
            },
        )
        reply = radius_client.SendPacket(stop)
        assert reply.code == pyrad.packet.AccountingResponse
