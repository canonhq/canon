"""Tests for API key generation and the api_key_routes."""

from __future__ import annotations

import hashlib

from canon.db.user_store import API_KEY_PREFIX, generate_api_key


class TestGenerateApiKey:
    def test_prefix(self):
        raw, _hash = generate_api_key()
        assert raw.startswith(API_KEY_PREFIX)

    def test_hash_matches(self):
        raw, key_hash = generate_api_key()
        assert key_hash == hashlib.sha256(raw.encode()).hexdigest()

    def test_unique(self):
        keys = {generate_api_key()[0] for _ in range(20)}
        assert len(keys) == 20

    def test_key_length(self):
        raw, _ = generate_api_key()
        # sw_ + base64url(32 bytes) ≈ 46 chars
        assert len(raw) > 40
