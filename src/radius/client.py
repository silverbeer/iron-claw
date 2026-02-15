"""RADIUS session client wrapping pyrad for iron-claw scraper sessions."""

from __future__ import annotations

import uuid
from pathlib import Path

import pyrad.packet
import structlog
from pyrad.client import Client
from pyrad.dictionary import Dictionary

from radius.models import AccountingUpdate, RadiusConfig, SessionGrant

logger = structlog.get_logger()

VENDOR_MISSTABLE = "MissTable"


def _load_dictionary() -> Dictionary:
    """Load the pyrad dictionary with standard + MissTable VSAs."""
    dict_path = Path(__file__).parent / "dictionary"
    return Dictionary(str(dict_path))


class RadiusSessionClient:
    """Manages RADIUS AAA lifecycle for a scraper session.

    Handles authentication (Access-Request), and accounting
    (Start/Interim/Stop) against a FreeRADIUS server with custom
    MissTable vendor-specific attributes.
    """

    def __init__(self, config: RadiusConfig | None = None) -> None:
        self.config = config or RadiusConfig()
        self._dict = _load_dictionary()
        self._client = Client(
            server=self.config.server,
            secret=self.config.secret.encode(),
            dict=self._dict,
            authport=self.config.auth_port,
            acctport=self.config.acct_port,
        )
        self._client.retries = self.config.retries
        self._client.timeout = self.config.timeout

    def authenticate(self, username: str, password: str) -> SessionGrant:
        """Send Access-Request and parse the Access-Accept into a SessionGrant.

        Raises:
            AuthenticationError: If Access-Reject is received.
            TimeoutError: If no response within timeout.
        """
        req = self._client.CreateAuthPacket(
            code=pyrad.packet.AccessRequest,
            User_Name=username,
            NAS_Identifier="iron-claw",
        )
        req["User-Password"] = req.PwCrypt(password)

        logger.info("radius.auth.request", username=username)
        reply = self._client.SendPacket(req)

        if reply.code == pyrad.packet.AccessReject:
            msg = "Access-Reject received"
            logger.warning("radius.auth.rejected", username=username)
            raise AuthenticationError(msg)

        if reply.code != pyrad.packet.AccessAccept:
            msg = f"Unexpected RADIUS response code: {reply.code}"
            raise AuthenticationError(msg)

        grant = self._parse_grant(reply)
        logger.info(
            "radius.auth.accepted",
            username=username,
            token_budget=grant.token_budget,
            model=grant.model_allowed,
            max_pages=grant.max_pages,
        )
        return grant

    def generate_session_id(self) -> str:
        """Generate a unique session ID for accounting."""
        return uuid.uuid4().hex[:16]

    def acct_start(self, session_id: str, username: str) -> bool:
        """Send Accounting-Request with Status-Type=Start."""
        req = self._create_acct_packet(session_id, username, "Start")
        logger.info("radius.acct.start", session_id=session_id, username=username)
        reply = self._client.SendPacket(req)
        return reply.code == pyrad.packet.AccountingResponse

    def acct_interim(self, session_id: str, username: str, update: AccountingUpdate) -> bool:
        """Send Accounting-Request with Status-Type=Interim-Update."""
        req = self._create_acct_packet(session_id, username, "Interim-Update")
        req["Acct-Session-Time"] = update.session_time
        # Repurpose Acct-Input-Octets for token count (documented convention)
        req["Acct-Input-Octets"] = update.tokens_used
        req["Acct-Output-Octets"] = update.matches_found

        logger.info(
            "radius.acct.interim",
            session_id=session_id,
            tokens_used=update.tokens_used,
            pages_visited=update.pages_visited,
        )
        reply = self._client.SendPacket(req)
        return reply.code == pyrad.packet.AccountingResponse

    def acct_stop(
        self,
        session_id: str,
        username: str,
        update: AccountingUpdate,
        terminate_cause: str = "User-Request",
    ) -> bool:
        """Send Accounting-Request with Status-Type=Stop."""
        req = self._create_acct_packet(session_id, username, "Stop")
        req["Acct-Session-Time"] = update.session_time
        req["Acct-Input-Octets"] = update.tokens_used
        req["Acct-Output-Octets"] = update.matches_found
        req["Acct-Terminate-Cause"] = terminate_cause

        logger.info(
            "radius.acct.stop",
            session_id=session_id,
            tokens_used=update.tokens_used,
            pages_visited=update.pages_visited,
            matches_found=update.matches_found,
            terminate_cause=terminate_cause,
        )
        reply = self._client.SendPacket(req)
        return reply.code == pyrad.packet.AccountingResponse

    def _create_acct_packet(
        self, session_id: str, username: str, status_type: str
    ) -> pyrad.packet.Packet:
        """Build an Accounting-Request with required AVPs."""
        req = self._client.CreateAcctPacket(code=pyrad.packet.AccountingRequest)
        req["User-Name"] = username
        req["Acct-Session-Id"] = session_id
        req["Acct-Status-Type"] = status_type
        req["NAS-Identifier"] = "iron-claw"
        req["NAS-IP-Address"] = "127.0.0.1"
        return req

    def _parse_grant(self, reply: pyrad.packet.Packet) -> SessionGrant:
        """Extract VSA grant attributes from an Access-Accept reply."""
        kwargs: dict = {}

        # Standard attributes
        if "Session-Timeout" in reply:
            kwargs["session_timeout"] = reply["Session-Timeout"][0]

        # MissTable VSAs
        vsa_map = {
            "MT-Token-Budget": "token_budget",
            "MT-Model-Allowed": "model_allowed",
            "MT-Allowed-Domains": "allowed_domains",
            "MT-Browser-Enabled": "browser_enabled",
            "MT-Shell-Enabled": "shell_enabled",
            "MT-Max-Pages": "max_pages",
            "MT-Max-LLM-Calls": "max_llm_calls",
            "MT-Output-Queue": "output_queue",
            "MT-Monthly-Budget": "monthly_budget",
            "MT-Monthly-Used": "monthly_used",
        }

        for attr_name, field_name in vsa_map.items():
            if attr_name in reply:
                value = reply[attr_name][0]
                # Convert integer 0/1 to bool for boolean fields
                if field_name in ("browser_enabled", "shell_enabled"):
                    value = bool(value)
                kwargs[field_name] = value

        return SessionGrant(**kwargs)


class AuthenticationError(Exception):
    """Raised when RADIUS authentication fails."""
