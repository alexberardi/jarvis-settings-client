"""Superuser JWT validation for settings write operations.

Provides a factory that creates a FastAPI dependency to validate superuser JWTs
by calling jarvis-auth's /auth/me endpoint. No shared secrets needed -- the JWT
secret stays in jarvis-auth only.
"""

import logging
from typing import Any, Callable

import httpx
from fastapi import Header, HTTPException, status

logger = logging.getLogger(__name__)


def create_superuser_auth(auth_service_url: str) -> Callable[..., Any]:
    """Create a FastAPI dependency that validates superuser JWT via jarvis-auth.

    Calls GET /auth/me on jarvis-auth with the Bearer token from the request.
    Checks the is_superuser field in the response.

    Args:
        auth_service_url: Base URL of jarvis-auth (e.g. "http://localhost:8007")

    Returns:
        A FastAPI dependency function.
    """
    auth_url = auth_service_url.rstrip("/")

    def require_superuser_jwt(
        authorization: str | None = Header(None),
    ) -> dict[str, Any]:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid Authorization header",
            )

        token = authorization[7:]

        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(
                    f"{auth_url}/auth/me",
                    headers={"Authorization": f"Bearer {token}"},
                )
        except httpx.RequestError as exc:
            logger.error("Failed to reach jarvis-auth for JWT validation: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unable to validate credentials: auth service unreachable",
            ) from exc

        if resp.status_code == 401:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
            )

        if resp.status_code != 200:
            logger.error(
                "Unexpected response from jarvis-auth /auth/me: %s %s",
                resp.status_code,
                resp.text[:200],
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Unexpected response from auth service",
            )

        user_data = resp.json()
        if not user_data.get("is_superuser"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Superuser access required",
            )

        return {
            "auth_type": "superuser_jwt",
            "user_id": user_data.get("id"),
            "email": user_data.get("email"),
        }

    return require_superuser_jwt
