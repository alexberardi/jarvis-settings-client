"""Tests for jarvis_settings_client.auth module."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from jarvis_settings_client.auth import (
    _resolve_url,
    create_combined_auth,
    create_superuser_auth,
)


# ===========================================================================
# _resolve_url
# ===========================================================================


class TestResolveUrl:
    """Tests for _resolve_url helper."""

    def test_static_string(self):
        assert _resolve_url("http://localhost:8007") == "http://localhost:8007"

    def test_static_string_strips_trailing_slash(self):
        assert _resolve_url("http://localhost:8007/") == "http://localhost:8007"

    def test_callable_url(self):
        assert _resolve_url(lambda: "http://auth:8007") == "http://auth:8007"

    def test_callable_url_strips_trailing_slash(self):
        assert _resolve_url(lambda: "http://auth:8007/") == "http://auth:8007"


# ===========================================================================
# create_superuser_auth
# ===========================================================================


class TestSuperuserAuth:
    """Tests for create_superuser_auth dependency."""

    def _make_app(self, auth_url: str = "http://auth:8007") -> FastAPI:
        app = FastAPI()
        dep = create_superuser_auth(auth_url)

        @app.get("/protected")
        def protected(auth=app.dependency_overrides.get(dep) or dep):  # noqa: B008
            return {"ok": True}

        # Simpler: just mount a route that uses the dep directly
        return app, dep

    def _app_with_route(self, auth_url: str = "http://auth:8007"):
        """Create a FastAPI app with a protected route using superuser auth."""
        app = FastAPI()
        dep = create_superuser_auth(auth_url)

        @app.get("/protected", dependencies=[])
        def protected(user=dep(authorization="Bearer test")):  # noqa: B008
            return {"ok": True}

        return app

    def test_missing_authorization_header(self):
        dep = create_superuser_auth("http://auth:8007")
        with pytest.raises(HTTPException) as exc_info:
            dep(authorization=None)
        assert exc_info.value.status_code == 401
        assert "Missing or invalid" in exc_info.value.detail

    def test_invalid_authorization_scheme(self):
        dep = create_superuser_auth("http://auth:8007")
        with pytest.raises(HTTPException) as exc_info:
            dep(authorization="Basic abc123")
        assert exc_info.value.status_code == 401

    @patch("jarvis_settings_client.auth.httpx.Client")
    def test_valid_superuser_token(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": 1,
            "email": "admin@example.com",
            "is_superuser": True,
        }
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_cls.return_value = mock_client

        dep = create_superuser_auth("http://auth:8007")
        result = dep(authorization="Bearer valid-token")

        assert result["auth_type"] == "superuser_jwt"
        assert result["user_id"] == 1
        assert result["email"] == "admin@example.com"
        mock_client.get.assert_called_once_with(
            "http://auth:8007/auth/me",
            headers={"Authorization": "Bearer valid-token"},
        )

    @patch("jarvis_settings_client.auth.httpx.Client")
    def test_non_superuser_token_returns_403(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": 2,
            "email": "user@example.com",
            "is_superuser": False,
        }
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_cls.return_value = mock_client

        dep = create_superuser_auth("http://auth:8007")
        with pytest.raises(HTTPException) as exc_info:
            dep(authorization="Bearer non-super-token")
        assert exc_info.value.status_code == 403
        assert "Superuser" in exc_info.value.detail

    @patch("jarvis_settings_client.auth.httpx.Client")
    def test_expired_token_returns_401(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_cls.return_value = mock_client

        dep = create_superuser_auth("http://auth:8007")
        with pytest.raises(HTTPException) as exc_info:
            dep(authorization="Bearer expired-token")
        assert exc_info.value.status_code == 401
        assert "Invalid or expired" in exc_info.value.detail

    @patch("jarvis_settings_client.auth.httpx.Client")
    def test_unexpected_auth_response_returns_502(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_cls.return_value = mock_client

        dep = create_superuser_auth("http://auth:8007")
        with pytest.raises(HTTPException) as exc_info:
            dep(authorization="Bearer some-token")
        assert exc_info.value.status_code == 502
        assert "Unexpected response" in exc_info.value.detail

    @patch("jarvis_settings_client.auth.httpx.Client")
    def test_auth_service_unreachable_returns_502(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.side_effect = httpx.ConnectError("Connection refused")
        mock_client_cls.return_value = mock_client

        dep = create_superuser_auth("http://auth:8007")
        with pytest.raises(HTTPException) as exc_info:
            dep(authorization="Bearer some-token")
        assert exc_info.value.status_code == 502
        assert "unreachable" in exc_info.value.detail

    @patch("jarvis_settings_client.auth.httpx.Client")
    def test_callable_url_is_resolved(self, mock_client_cls):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": 1,
            "email": "admin@example.com",
            "is_superuser": True,
        }
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_cls.return_value = mock_client

        dep = create_superuser_auth(lambda: "http://dynamic-auth:9000/")
        dep(authorization="Bearer valid-token")

        mock_client.get.assert_called_once_with(
            "http://dynamic-auth:9000/auth/me",
            headers={"Authorization": "Bearer valid-token"},
        )


# ===========================================================================
# create_combined_auth
# ===========================================================================


class TestCombinedAuth:
    """Tests for create_combined_auth dependency."""

    def _make_app(self, auth_url: str = "http://auth:8007"):
        """Create a FastAPI app with combined auth on a protected route."""
        app = FastAPI()
        dep = create_combined_auth(auth_url)

        @app.get("/protected")
        async def protected(auth=dep):  # noqa: B008
            return auth

        return app

    def test_no_credentials_returns_401(self):
        """Request without any credentials is rejected."""
        app = FastAPI()
        dep = create_combined_auth("http://auth:8007")

        @app.get("/protected")
        async def protected(
            request=None,
            authorization=None,
            x_jarvis_app_id=None,
            x_jarvis_app_key=None,
        ):
            return await dep(
                request=MagicMock(),
                authorization=authorization,
                x_jarvis_app_id=x_jarvis_app_id,
                x_jarvis_app_key=x_jarvis_app_key,
            )

        client = TestClient(app)
        # Call the dep directly
        with pytest.raises(HTTPException) as exc_info:
            import asyncio
            asyncio.get_event_loop().run_until_complete(
                dep(
                    request=MagicMock(),
                    authorization=None,
                    x_jarvis_app_id=None,
                    x_jarvis_app_key=None,
                )
            )
        assert exc_info.value.status_code == 401
        assert "Missing authentication" in exc_info.value.detail

    @patch("jarvis_settings_client.auth.httpx.Client")
    def test_bearer_token_delegates_to_superuser_auth(self, mock_client_cls):
        """Bearer token is validated via superuser auth path."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "id": 1,
            "email": "admin@example.com",
            "is_superuser": True,
        }
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get.return_value = mock_response
        mock_client_cls.return_value = mock_client

        dep = create_combined_auth("http://auth:8007")

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            dep(
                request=MagicMock(),
                authorization="Bearer valid-token",
                x_jarvis_app_id=None,
                x_jarvis_app_key=None,
            )
        )

        assert result["auth_type"] == "superuser_jwt"
        assert result["user_id"] == 1

    @patch("jarvis_settings_client.auth.httpx.AsyncClient")
    def test_app_credentials_validated(self, mock_async_client_cls):
        """App credentials are validated via /internal/app-ping."""
        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_async_client_cls.return_value = mock_client

        dep = create_combined_auth("http://auth:8007")

        import asyncio
        result = asyncio.get_event_loop().run_until_complete(
            dep(
                request=MagicMock(),
                authorization=None,
                x_jarvis_app_id="my-app",
                x_jarvis_app_key="my-key",
            )
        )
        assert result["auth_type"] == "app_credentials"
        assert result["app_id"] == "my-app"

    @patch("jarvis_settings_client.auth.httpx.AsyncClient")
    def test_invalid_app_credentials_returns_401(self, mock_async_client_cls):
        """Invalid app credentials are rejected."""
        mock_response = MagicMock()
        mock_response.status_code = 401

        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_async_client_cls.return_value = mock_client

        dep = create_combined_auth("http://auth:8007")

        import asyncio
        with pytest.raises(HTTPException) as exc_info:
            asyncio.get_event_loop().run_until_complete(
                dep(
                    request=MagicMock(),
                    authorization=None,
                    x_jarvis_app_id="bad-app",
                    x_jarvis_app_key="bad-key",
                )
            )
        assert exc_info.value.status_code == 401
        assert "Invalid app credentials" in exc_info.value.detail

    @patch("jarvis_settings_client.auth.httpx.AsyncClient")
    def test_app_ping_unreachable_returns_502(self, mock_async_client_cls):
        """Auth service unreachable during app-ping returns 502."""
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
        mock_async_client_cls.return_value = mock_client

        dep = create_combined_auth("http://auth:8007")

        import asyncio
        with pytest.raises(HTTPException) as exc_info:
            asyncio.get_event_loop().run_until_complete(
                dep(
                    request=MagicMock(),
                    authorization=None,
                    x_jarvis_app_id="my-app",
                    x_jarvis_app_key="my-key",
                )
            )
        assert exc_info.value.status_code == 502
        assert "unreachable" in exc_info.value.detail
