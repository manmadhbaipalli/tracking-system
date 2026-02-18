"""Tests for middleware: correlation ID, logging, and error handling."""
import json
import logging

import pytest

from app.middleware.correlation import get_request_id


# ---------------------------------------------------------------------------
# Correlation middleware
# ---------------------------------------------------------------------------

class TestCorrelationMiddleware:
    def test_request_id_in_response_header(self, client):
        resp = client.get("/health")
        assert "x-request-id" in resp.headers

    def test_client_supplied_request_id_is_echoed(self, client):
        custom_id = "my-custom-request-id-123"
        resp = client.get("/health", headers={"X-Request-ID": custom_id})
        assert resp.headers["x-request-id"] == custom_id

    def test_auto_generated_request_id_is_unique(self, client):
        ids = {client.get("/health").headers["x-request-id"] for _ in range(5)}
        assert len(ids) == 5

    def test_get_request_id_outside_request_returns_empty(self):
        # Outside a request context the ContextVar should return the default
        assert get_request_id() == ""


# ---------------------------------------------------------------------------
# Error handler middleware
# ---------------------------------------------------------------------------

class TestErrorHandlerMiddleware:
    def test_app_exception_returns_structured_json(self, client, registered_user):
        """A duplicate registration triggers ConflictError → structured JSON body."""
        resp = client.post(
            "/auth/register",
            json={"email": "test@example.com", "password": "Secr3tPass!"},
        )
        assert resp.status_code == 409
        body = resp.json()
        assert "error" in body
        assert "code" in body["error"]
        assert "message" in body["error"]
        assert "request_id" in body

    def test_error_response_has_request_id(self, client, registered_user):
        resp = client.post(
            "/auth/register",
            json={"email": "test@example.com", "password": "Secr3tPass!"},
        )
        body = resp.json()
        assert body["request_id"]  # non-empty

    def test_validation_error_422(self, client):
        resp = client.post("/auth/register", json={})
        assert resp.status_code == 422

    def test_stack_trace_not_exposed(self, client, registered_user):
        """Internal error details must not leak to the client."""
        resp = client.post(
            "/auth/register",
            json={"email": "test@example.com", "password": "Secr3tPass!"},
        )
        text = resp.text
        assert "Traceback" not in text
        assert "traceback" not in text

    def test_auth_error_code_in_response(self, client):
        resp = client.post(
            "/auth/login",
            json={"email": "nobody@example.com", "password": "WrongPass!"},
        )
        body = resp.json()
        assert body["error"]["code"] == "AUTH_INVALID_CREDENTIALS"


# ---------------------------------------------------------------------------
# Logging middleware (smoke test via caplog)
# ---------------------------------------------------------------------------

class TestLoggingMiddleware:
    def test_request_is_logged(self, client, caplog):
        with caplog.at_level(logging.INFO, logger="app.access"):
            client.get("/health")
        messages = [r.message for r in caplog.records]
        assert any("Request started" in m or "Request finished" in m for m in messages)

    def test_status_code_logged(self, client, caplog):
        with caplog.at_level(logging.INFO, logger="app.access"):
            client.get("/health")
        # At least one record should have a status_code extra field
        status_codes = [
            getattr(r, "status_code", None)
            for r in caplog.records
            if hasattr(r, "status_code")
        ]
        assert 200 in status_codes


# ---------------------------------------------------------------------------
# JSON formatter unit tests
# ---------------------------------------------------------------------------

class TestJsonFormatter:
    def test_formatter_produces_valid_json(self, caplog):
        from app.logging_config import JsonFormatter

        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello world",
            args=(),
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["level"] == "INFO"
        assert parsed["message"] == "hello world"
        assert "timestamp" in parsed

    def test_formatter_includes_extra_fields(self, caplog):
        from app.logging_config import JsonFormatter

        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="with extra",
            args=(),
            exc_info=None,
        )
        record.user_id = 99
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed.get("user_id") == 99

    def test_formatter_exc_info(self, caplog):
        from app.logging_config import JsonFormatter

        formatter = JsonFormatter()
        try:
            raise ValueError("boom")
        except ValueError:
            import sys
            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="",
            lineno=0,
            msg="error occurred",
            args=(),
            exc_info=exc_info,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert "exc_info" in parsed
        assert "ValueError" in parsed["exc_info"]


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    def test_health_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
