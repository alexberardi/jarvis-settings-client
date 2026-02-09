"""FastAPI routes for settings management.

Provides a router factory that creates settings endpoints with configurable
authentication. All endpoints require authentication by default.
"""

from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from jarvis_settings_client.service import SettingsService


# ===========================================================================
# Request/Response Models
# ===========================================================================


class SettingUpdate(BaseModel):
    """Request to update a single setting."""

    value: Any


class SettingResponse(BaseModel):
    """Response for a single setting."""

    key: str
    value: Any
    value_type: str
    category: str
    description: str | None
    requires_reload: bool
    is_secret: bool
    env_fallback: str | None = None
    from_db: bool


class SettingsListResponse(BaseModel):
    """Response for listing settings."""

    settings: list[SettingResponse]
    total: int


class CategoriesResponse(BaseModel):
    """Response for listing categories."""

    categories: list[str]


class SyncResponse(BaseModel):
    """Response for sync operation."""

    synced: dict[str, bool]
    total_synced: int
    total_skipped: int


class UpdateResponse(BaseModel):
    """Response for update operation."""

    success: bool
    key: str
    requires_reload: bool
    message: str | None = None


class CacheInvalidateResponse(BaseModel):
    """Response for cache invalidation."""

    status: str
    invalidated: str


# ===========================================================================
# Default Auth (rejects all requests)
# ===========================================================================


def _default_auth_dependency() -> None:
    """Default auth that rejects all requests.

    Services must provide their own auth dependency.
    """
    raise HTTPException(
        status_code=401,
        detail={
            "error": {
                "type": "unauthorized",
                "message": "Authentication required",
                "code": "unauthorized",
            }
        },
    )


# ===========================================================================
# Router Factory
# ===========================================================================


def create_settings_router(
    service: SettingsService,
    auth_dependency: Callable[[], Any] | None = None,
    write_auth_dependency: Callable[[], Any] | None = None,
    prefix: str = "",
    tags: list[str] | None = None,
) -> APIRouter:
    """Create a FastAPI router for settings endpoints.

    Args:
        service: SettingsService instance to use
        auth_dependency: FastAPI dependency for authentication on read endpoints.
            If None, uses a default that rejects all requests.
            Typically this should be your app-to-app auth dependency.
        write_auth_dependency: FastAPI dependency for authentication on write
            endpoints (PUT, POST). If None, falls back to auth_dependency.
            Typically this should be a superuser JWT auth dependency.
        prefix: URL prefix for routes (default: no prefix)
        tags: OpenAPI tags for the router

    Returns:
        Configured APIRouter

    Example:
        from jarvis_settings_client import create_settings_router, SettingsService
        from your_auth import require_app_client

        service = SettingsService(definitions=MY_SETTINGS, get_db_session=get_db)
        router = create_settings_router(
            service=service,
            auth_dependency=require_app_client,
        )
        app.include_router(router, prefix="/settings")
    """
    router = APIRouter(prefix=prefix, tags=tags or ["settings"])

    # Use provided auth or default (which rejects all)
    auth = auth_dependency or _default_auth_dependency
    write_auth = write_auth_dependency or auth

    @router.get("/", response_model=SettingsListResponse)
    def list_settings(
        category: str | None = Query(None, description="Filter by category"),
        household_id: str | None = Query(None, description="Household scope"),
        node_id: str | None = Query(None, description="Node scope"),
        user_id: int | None = Query(None, description="User scope"),
        _auth: Any = Depends(auth),
    ) -> SettingsListResponse:
        """List all settings.

        Optionally filter by category using the `category` query parameter.
        Scope parameters control which values are returned (cascade lookup).
        """
        settings = service.list_all(
            category=category,
            household_id=household_id,
            node_id=node_id,
            user_id=user_id,
        )

        return SettingsListResponse(
            settings=[SettingResponse(**s) for s in settings],
            total=len(settings),
        )

    @router.get("/categories", response_model=CategoriesResponse)
    def list_categories(
        _auth: Any = Depends(auth),
    ) -> CategoriesResponse:
        """List all unique setting categories."""
        categories = service.list_categories()
        return CategoriesResponse(categories=categories)

    @router.get("/{key:path}", response_model=SettingResponse)
    def get_setting(
        key: str,
        household_id: str | None = Query(None, description="Household scope"),
        node_id: str | None = Query(None, description="Node scope"),
        user_id: int | None = Query(None, description="User scope"),
        _auth: Any = Depends(auth),
    ) -> SettingResponse:
        """Get a single setting by key.

        The key uses dot notation, e.g., `model.main.name`.
        """
        # Check if key exists in definitions
        if key not in service.definitions:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": {
                        "type": "not_found",
                        "message": f"Setting not found: {key}",
                        "code": "not_found",
                    }
                },
            )

        definition = service.definitions[key]
        value = service.get(
            key,
            household_id=household_id,
            node_id=node_id,
            user_id=user_id,
        )

        # Check if it's from DB
        cache_key = service._make_cache_key(key, household_id, node_id, user_id)
        with service._cache_lock:
            from_db = (
                cache_key in service._cache and service._cache[cache_key].from_db
            )

        # Mask secrets
        display_value = value
        if definition.is_secret and value:
            display_value = "********"

        return SettingResponse(
            key=key,
            value=display_value,
            value_type=definition.value_type,
            category=definition.category,
            description=definition.description,
            requires_reload=definition.requires_reload,
            is_secret=definition.is_secret,
            env_fallback=definition.env_fallback,
            from_db=from_db,
        )

    @router.put("/{key:path}", response_model=UpdateResponse)
    def update_setting(
        key: str,
        body: SettingUpdate,
        household_id: str | None = Query(None, description="Household scope"),
        node_id: str | None = Query(None, description="Node scope"),
        user_id: int | None = Query(None, description="User scope"),
        _auth: Any = Depends(write_auth),
    ) -> UpdateResponse:
        """Update a single setting.

        If the setting has `requires_reload=True`, the service will need to be
        restarted for the change to take effect. The response indicates this.
        """
        # Check if key exists
        if key not in service.definitions:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": {
                        "type": "not_found",
                        "message": f"Setting not found: {key}",
                        "code": "not_found",
                    }
                },
            )

        definition = service.definitions[key]
        success = service.set(
            key,
            body.value,
            household_id=household_id,
            node_id=node_id,
            user_id=user_id,
        )

        if not success:
            raise HTTPException(
                status_code=500,
                detail={
                    "error": {
                        "type": "internal_error",
                        "message": f"Failed to update setting: {key}",
                        "code": "update_failed",
                    }
                },
            )

        message = None
        if definition.requires_reload:
            message = "Service restart required for this change to take effect"

        return UpdateResponse(
            success=True,
            key=key,
            requires_reload=definition.requires_reload,
            message=message,
        )

    @router.post("/sync-from-env", response_model=SyncResponse)
    def sync_from_env(
        _auth: Any = Depends(write_auth),
    ) -> SyncResponse:
        """One-time migration: sync settings from environment variables to database.

        This reads all defined settings from environment variables and writes
        them to the database. Useful for initial setup or migration.
        """
        results = service.sync_from_env()

        total_synced = sum(1 for v in results.values() if v)
        total_skipped = sum(1 for v in results.values() if not v)

        return SyncResponse(
            synced=results,
            total_synced=total_synced,
            total_skipped=total_skipped,
        )

    @router.post("/invalidate-cache", response_model=CacheInvalidateResponse)
    def invalidate_cache(
        key: str | None = Query(None, description="Key to invalidate (all if omitted)"),
        _auth: Any = Depends(write_auth),
    ) -> CacheInvalidateResponse:
        """Invalidate the settings cache.

        If `key` is provided, only that key is invalidated.
        Otherwise, the entire cache is cleared.
        """
        service.invalidate_cache(key)
        return CacheInvalidateResponse(status="ok", invalidated=key or "all")

    return router
