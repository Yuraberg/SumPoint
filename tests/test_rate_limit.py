"""Unit tests for the X-Forwarded-For based rate-limit key function.

Caddy appends the peer address it observes to X-Forwarded-For rather than
replacing it, so the LAST entry is the one Caddy computed from the raw TCP
connection (trustworthy); any earlier entries are attacker-supplied header
text. Picking the first entry would let a client dodge the /auth rate limit
by rotating a fake leading IP.
"""
from types import SimpleNamespace

from app.rate_limit import _client_ip


def _request(headers: dict, client_host: str = "10.0.0.1"):
    return SimpleNamespace(
        headers=headers,
        client=SimpleNamespace(host=client_host),
    )


def test_no_forwarded_header_falls_back_to_remote_address():
    req = _request({}, client_host="203.0.113.5")
    assert _client_ip(req) == "203.0.113.5"


def test_single_hop_uses_that_ip():
    req = _request({"X-Forwarded-For": "198.51.100.7"})
    assert _client_ip(req) == "198.51.100.7"


def test_multi_hop_uses_last_entry_not_first():
    # Attacker sets X-Forwarded-For: <fake>; Caddy appends the real peer IP.
    req = _request({"X-Forwarded-For": "1.2.3.4, 198.51.100.7"})
    assert _client_ip(req) == "198.51.100.7"


def test_strips_whitespace_around_entries():
    req = _request({"X-Forwarded-For": "1.2.3.4,  198.51.100.7  "})
    assert _client_ip(req) == "198.51.100.7"


def test_spoofed_leading_ip_does_not_change_key():
    # Two "requests" differing only in the attacker-controlled first hop must
    # resolve to the same rate-limit key, since Caddy's own appended IP (last)
    # is identical.
    req_a = _request({"X-Forwarded-For": "1.1.1.1, 198.51.100.7"})
    req_b = _request({"X-Forwarded-For": "9.9.9.9, 198.51.100.7"})
    assert _client_ip(req_a) == _client_ip(req_b)
