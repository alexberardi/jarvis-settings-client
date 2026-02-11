"""Auth utilities for settings endpoints.

Provides factories that create FastAPI dependencies for:
- Superuser JWT validation via jarvis-auth /auth/me
- Combined auth that accepts either Bearer token OR app-to-app credentials
"""

import logging
from typing import Any, Callable

import httpx
from fastapi import Header, HTTPException, Request, status

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


def create_combined_auth(auth_service_url: str) -> Callable[..., Any]:
    """Create a FastAPI dependency that accepts either superuser JWT or app credentials.

    Checks for a Bearer token first (validated via jarvis-auth /auth/me as superuser).
    If no Bearer token, checks for app-to-app credentials (X-Jarvis-App-Id +
    X-Jarvis-App-Key) validated via jarvis-auth /internal/app-ping.

    Args:
        auth_service_url: Base URL of jarvis-auth (e.g. "http://localhost:8007")

    Returns:
        A FastAPI dependency function.
    """
    auth_url = auth_service_url.rstrip("/")
    superuser_dep = create_superuser_auth(auth_service_url)

    async def combined_auth(
        request: Request,
        authorization: str | None = Header(None),
        x_jarvis_app_id: str | None = Header(None),
        x_jarvis_app_key: str | None = Header(None),
    ) -> dict[str, Any]:
        # Try Bearer token first
        if authorization and authorization.startswith("Bearer "):
            return superuser_dep(authorization=authorization)

        # Try app-to-app credentials
        if x_jarvis_app_id and x_jarvis_app_key:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.get(
                        f"{auth_url}/internal/app-ping",
                        headers={
                            "X-Jarvis-App-Id": x_jarvis_app_id,
                            "X-Jarvis-App-Key": x_jarvis_app_key,
                        },
                    )
            except httpx.RequestError as exc:
                logger.error("Failed to reach jarvis-auth for app-ping: %s", exc)
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Unable to validate credentials: auth service unreachable",
                ) from exc

            if resp.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid app credentials",
                )

            return {"auth_type": "app_credentials", "app_id": x_jarvis_app_id}

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication. Provide either Bearer token or app credentials.",
        )

    return combined_auth
