"""
PROMPT: Generate tests for dashboard HTML endpoint.

CHANGES MADE: None (AI-generated tests for dashboard).
"""

import pytest


class TestDashboard:
    def test_dashboard_returns_200(self, client):
        resp = client.get("/dashboard")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")

    def test_dashboard_contains_store_title(self, client):
        resp = client.get("/dashboard")
        html = resp.text.lower()
        assert "store" in html or "purplle" in html or "intelligence" in html
