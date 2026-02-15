"""Authentication tests for iron-claw RADIUS (Access-Request -> Accept/Reject)."""

from __future__ import annotations

import pyrad.packet
import pytest


class TestValidAuthentication:
    """Tests for valid credentials — expect Access-Accept with VSA grants."""

    @pytest.mark.integration
    def test_valid_user_authenticates(self, radius_client):
        req = radius_client.CreateAuthPacket(
            code=pyrad.packet.AccessRequest,
            User_Name="iron-claw-scraper",
            NAS_Identifier="iron-claw",
        )
        req["User-Password"] = req.PwCrypt("scraper-secret")
        reply = radius_client.SendPacket(req)
        assert reply.code == pyrad.packet.AccessAccept

    @pytest.mark.integration
    def test_valid_user_gets_session_timeout(self, radius_client):
        req = radius_client.CreateAuthPacket(
            code=pyrad.packet.AccessRequest,
            User_Name="iron-claw-scraper",
            NAS_Identifier="iron-claw",
        )
        req["User-Password"] = req.PwCrypt("scraper-secret")
        reply = radius_client.SendPacket(req)
        assert reply["Session-Timeout"] == [1800]

    @pytest.mark.integration
    def test_valid_user_gets_token_budget(self, radius_client):
        req = radius_client.CreateAuthPacket(
            code=pyrad.packet.AccessRequest,
            User_Name="iron-claw-scraper",
            NAS_Identifier="iron-claw",
        )
        req["User-Password"] = req.PwCrypt("scraper-secret")
        reply = radius_client.SendPacket(req)
        assert reply["MT-Token-Budget"] == [50000]

    @pytest.mark.integration
    def test_valid_user_gets_model_allowed(self, radius_client):
        req = radius_client.CreateAuthPacket(
            code=pyrad.packet.AccessRequest,
            User_Name="iron-claw-scraper",
            NAS_Identifier="iron-claw",
        )
        req["User-Password"] = req.PwCrypt("scraper-secret")
        reply = radius_client.SendPacket(req)
        assert reply["MT-Model-Allowed"] == ["claude-haiku-4-5"]

    @pytest.mark.integration
    def test_valid_user_gets_max_pages(self, radius_client):
        req = radius_client.CreateAuthPacket(
            code=pyrad.packet.AccessRequest,
            User_Name="iron-claw-scraper",
            NAS_Identifier="iron-claw",
        )
        req["User-Password"] = req.PwCrypt("scraper-secret")
        reply = radius_client.SendPacket(req)
        assert reply["MT-Max-Pages"] == [20]


class TestInvalidAuthentication:
    """Tests for invalid credentials — expect Access-Reject."""

    @pytest.mark.integration
    def test_wrong_password_rejected(self, radius_client):
        req = radius_client.CreateAuthPacket(
            code=pyrad.packet.AccessRequest,
            User_Name="iron-claw-scraper",
            NAS_Identifier="iron-claw",
        )
        req["User-Password"] = req.PwCrypt("wrongpassword")
        reply = radius_client.SendPacket(req)
        assert reply.code == pyrad.packet.AccessReject

    @pytest.mark.integration
    def test_unknown_user_rejected(self, radius_client):
        req = radius_client.CreateAuthPacket(
            code=pyrad.packet.AccessRequest,
            User_Name="nonexistent_user",
            NAS_Identifier="iron-claw",
        )
        req["User-Password"] = req.PwCrypt("anypassword")
        reply = radius_client.SendPacket(req)
        assert reply.code == pyrad.packet.AccessReject

    @pytest.mark.integration
    def test_empty_password_rejected(self, radius_client):
        req = radius_client.CreateAuthPacket(
            code=pyrad.packet.AccessRequest,
            User_Name="iron-claw-scraper",
            NAS_Identifier="iron-claw",
        )
        req["User-Password"] = req.PwCrypt("")
        reply = radius_client.SendPacket(req)
        assert reply.code == pyrad.packet.AccessReject
