"""Tests for jarvis_settings_client.routes module.

TDD tests written FIRST before implementation.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from jarvis_settings_client.types import SettingDefinition


@pytest.fixture
def sample_definitions() -> list[SettingDefinition]:
    """Sample setting definitions for testing."""
    return [
        SettingDefinition(
            key="model.name",
            category="model",
            value_type="string",
            default="default-model",
            description="Model name",
            env_fallback="TEST_MODEL_NAME",
        ),
        SettingDefinition(
            key="model.context_window",
            category="model",
            value_type="int",
            default=8192,
            description="Context window size",
            env_fallback="TEST_CONTEXT_WINDOW",
        ),
        SettingDefinition(
            key="api.secret",
            category="api",
            value_type="string",
            default="",
            description="Secret key",
            is_secret=True,
        ),
    ]


@pytest.fixture
def mock_app_auth():
    """Mock app-to-app authentication that always succeeds."""
    mock_client = MagicMock()
    mock_client.app_id = "test-app"
    return mock_client


@pytest.fixture
def test_app(sample_definitions, mock_app_auth):
    """Create test FastAPI app with settings routes."""
    from jarvis_settings_client.routes import create_settings_router
    from jarvis_settings_client.service import SettingsService

    app = FastAPI()

    # Create mock service
    service = SettingsService(
        definitions=sample_definitions,
        get_db_session=lambda: None,
    )

    # Create router with mock auth
    router = create_settings_router(
        service=service,
        auth_dependency=lambda: mock_app_auth,
    )

    app.include_router(router, prefix="/settings")
    return app


@pytest.fixture
def client(test_app):
    """Test client for the FastAPI app."""
    return TestClient(test_app)


class TestSettingsRoutesAuth:
    """Tests for authentication on settings routes."""

    def test_list_requires_auth(self, sample_definitions):
        """Unauthenticated request to list returns 401."""
        from jarvis_settings_client.routes import create_settings_router
        from jarvis_settings_client.service import SettingsService

        app = FastAPI()
        service = SettingsService(
            definitions=sample_definitions,
            get_db_session=lambda: None,
        )

        # Create router WITHOUT providing auth dependency - uses default
        router = create_settings_router(service=service)
        app.include_router(router, prefix="/settings")

        client = TestClient(app)
        response = client.get("/settings/")

        assert response.status_code == 401

    def test_get_requires_auth(self, sample_definitions):
        """Unauthenticated request to get single setting returns 401."""
        from jarvis_settings_client.routes import create_settings_router
        from jarvis_settings_client.service import SettingsService

        app = FastAPI()
        service = SettingsService(
            definitions=sample_definitions,
            get_db_session=lambda: None,
        )

        router = create_settings_router(service=service)
        app.include_router(router, prefix="/settings")

        client = TestClient(app)
        response = client.get("/settings/model.name")

        assert response.status_code == 401

    def test_update_requires_auth(self, sample_definitions):
        """Unauthenticated request to update returns 401."""
        from jarvis_settings_client.routes import create_settings_router
        from jarvis_settings_client.service import SettingsService

        app = FastAPI()
        service = SettingsService(
            definitions=sample_definitions,
            get_db_session=lambda: None,
        )

        router = create_settings_router(service=service)
        app.include_router(router, prefix="/settings")

        client = TestClient(app)
        response = client.put("/settings/model.name", json={"value": "new-model"})

        assert response.status_code == 401


class TestSettingsRoutesList:
    """Tests for GET /settings endpoint."""

    def test_list_returns_all_settings(self, client):
        """Returns all defined settings with values."""
        response = client.get("/settings/")

        assert response.status_code == 200
        data = response.json()
        assert "settings" in data
        assert "total" in data
        assert data["total"] == 3

    def test_list_filters_by_category(self, client):
        """Can filter settings by category."""
        response = client.get("/settings/?category=model")

        assert response.status_code == 200
        data = response.json()
        assert all(s["category"] == "model" for s in data["settings"])
        assert data["total"] == 2  # model.name and model.context_window

    def test_list_includes_metadata(self, client):
        """Each setting includes full metadata."""
        response = client.get("/settings/")

        assert response.status_code == 200
        data = response.json()
        setting = data["settings"][0]

        assert "key" in setting
        assert "value" in setting
        assert "value_type" in setting
        assert "category" in setting
        assert "description" in setting
        assert "requires_reload" in setting
        assert "is_secret" in setting
        assert "from_db" in setting


class TestSettingsRoutesGet:
    """Tests for GET /settings/{key} endpoint."""

    def test_get_single_setting(self, client):
        """Get a single setting by key."""
        response = client.get("/settings/model.name")

        assert response.status_code == 200
        data = response.json()
        assert data["key"] == "model.name"
        assert data["value"] == "default-model"

    def test_get_unknown_key_returns_404(self, client):
        """Unknown setting key returns 404."""
        response = client.get("/settings/unknown.key")

        assert response.status_code == 404
        data = response.json()
        assert "error" in data["detail"]

    def test_get_masks_secret_value(self, client):
        """Secret values are masked in response."""
        response = client.get("/settings/api.secret")

        assert response.status_code == 200
        data = response.json()
        assert data["is_secret"] is True
        # Even default empty string should show masked for secrets
        # or the actual masked value if set


class TestSettingsRoutesUpdate:
    """Tests for PUT /settings/{key} endpoint."""

    def test_update_setting(self, test_app, mock_app_auth):
        """Update a setting value."""
        from jarvis_settings_client.routes import create_settings_router
        from jarvis_settings_client.service import SettingsService
        from jarvis_settings_client.types import SettingDefinition

        # Create app with mocked DB session
        app = FastAPI()
        definitions = [
            SettingDefinition(
                key="model.name",
                category="model",
                value_type="string",
                default="default",
                description="Test",
            ),
        ]

        # Mock Setting model class
        MockSetting = MagicMock()

        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None

        service = SettingsService(
            definitions=definitions,
            get_db_session=lambda: mock_session,
            setting_model=MockSetting,
        )

        router = create_settings_router(
            service=service,
            auth_dependency=lambda: mock_app_auth,
        )
        app.include_router(router, prefix="/settings")

        client = TestClient(app)
        response = client.put("/settings/model.name", json={"value": "new-model"})

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["key"] == "model.name"

    def test_update_unknown_key_returns_404(self, client):
        """Update unknown key returns 404."""
        response = client.put("/settings/unknown.key", json={"value": "test"})

        assert response.status_code == 404

    def test_update_returns_requires_reload(self, test_app, mock_app_auth):
        """Update response indicates if reload required."""
        from jarvis_settings_client.routes import create_settings_router
        from jarvis_settings_client.service import SettingsService
        from jarvis_settings_client.types import SettingDefinition

        app = FastAPI()
        definitions = [
            SettingDefinition(
                key="model.backend",
                category="model",
                value_type="string",
                default="gguf",
                description="Backend",
                requires_reload=True,
            ),
        ]

        # Mock Setting model class
        MockSetting = MagicMock()

        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None

        service = SettingsService(
            definitions=definitions,
            get_db_session=lambda: mock_session,
            setting_model=MockSetting,
        )

        router = create_settings_router(
            service=service,
            auth_dependency=lambda: mock_app_auth,
        )
        app.include_router(router, prefix="/settings")

        client = TestClient(app)
        response = client.put("/settings/model.backend", json={"value": "vllm"})

        assert response.status_code == 200
        data = response.json()
        assert data["requires_reload"] is True


class TestSettingsRoutesCategories:
    """Tests for GET /settings/categories endpoint."""

    def test_list_categories(self, client):
        """List unique categories."""
        response = client.get("/settings/categories")

        assert response.status_code == 200
        data = response.json()
        assert "categories" in data
        assert "api" in data["categories"]
        assert "model" in data["categories"]


class TestSettingsRoutesSyncFromEnv:
    """Tests for POST /settings/sync-from-env endpoint."""

    def test_sync_from_env(self, test_app, mock_app_auth):
        """Sync settings from environment variables."""
        from jarvis_settings_client.routes import create_settings_router
        from jarvis_settings_client.service import SettingsService
        from jarvis_settings_client.types import SettingDefinition

        app = FastAPI()
        definitions = [
            SettingDefinition(
                key="test.value",
                category="test",
                value_type="string",
                default="default",
                description="Test",
                env_fallback="TEST_VALUE",
            ),
        ]

        service = SettingsService(
            definitions=definitions,
            get_db_session=lambda: None,
        )

        router = create_settings_router(
            service=service,
            auth_dependency=lambda: mock_app_auth,
        )
        app.include_router(router, prefix="/settings")

        client = TestClient(app)
        response = client.post("/settings/sync-from-env")

        assert response.status_code == 200
        data = response.json()
        assert "synced" in data
        assert "total_synced" in data
        assert "total_skipped" in data


class TestSettingsRoutesInvalidateCache:
    """Tests for POST /settings/invalidate-cache endpoint."""

    def test_invalidate_all_cache(self, client):
        """Invalidate entire cache."""
        response = client.post("/settings/invalidate-cache")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["invalidated"] == "all"

    def test_invalidate_single_key_cache(self, client):
        """Invalidate cache for single key."""
        response = client.post("/settings/invalidate-cache?key=model.name")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["invalidated"] == "model.name"


class TestSettingsRoutesScopedQueries:
    """Tests for multi-tenant scoped queries."""

    def test_list_with_household_scope(self, test_app, mock_app_auth):
        """List settings scoped to household."""
        from jarvis_settings_client.routes import create_settings_router
        from jarvis_settings_client.service import SettingsService
        from jarvis_settings_client.types import SettingDefinition

        app = FastAPI()
        definitions = [
            SettingDefinition(
                key="test.value",
                category="test",
                value_type="string",
                default="default",
                description="Test",
            ),
        ]

        service = SettingsService(
            definitions=definitions,
            get_db_session=lambda: None,
        )

        router = create_settings_router(
            service=service,
            auth_dependency=lambda: mock_app_auth,
        )
        app.include_router(router, prefix="/settings")

        client = TestClient(app)
        response = client.get("/settings/?household_id=h123")

        assert response.status_code == 200

    def test_update_with_scope(self, test_app, mock_app_auth):
        """Update setting with scope parameters."""
        from jarvis_settings_client.routes import create_settings_router
        from jarvis_settings_client.service import SettingsService
        from jarvis_settings_client.types import SettingDefinition

        app = FastAPI()
        definitions = [
            SettingDefinition(
                key="test.value",
                category="test",
                value_type="string",
                default="default",
                description="Test",
            ),
        ]

        # Mock Setting model class
        MockSetting = MagicMock()

        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None

        service = SettingsService(
            definitions=definitions,
            get_db_session=lambda: mock_session,
            setting_model=MockSetting,
        )

        router = create_settings_router(
            service=service,
            auth_dependency=lambda: mock_app_auth,
        )
        app.include_router(router, prefix="/settings")

        client = TestClient(app)
        response = client.put(
            "/settings/test.value?household_id=h123&node_id=n456",
            json={"value": "scoped-value"},
        )

        assert response.status_code == 200
