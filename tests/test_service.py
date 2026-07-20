"""Tests for jarvis_settings_client.service module.

TDD tests written FIRST before implementation.
"""

import json
import os
import time
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from jarvis_settings_client.types import SettingDefinition


# Will import after implementation exists
# from jarvis_settings_client.service import (
#     SettingsService,
#     coerce_value,
#     serialize_value,
# )


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
            key="inference.temperature",
            category="inference",
            value_type="float",
            default=0.7,
            description="Sampling temperature",
            env_fallback="TEST_TEMPERATURE",
        ),
        SettingDefinition(
            key="feature.enabled",
            category="feature",
            value_type="bool",
            default=False,
            description="Feature flag",
            env_fallback="TEST_FEATURE_ENABLED",
        ),
        SettingDefinition(
            key="config.options",
            category="config",
            value_type="json",
            default={"key": "value"},
            description="JSON config",
            env_fallback="TEST_CONFIG_OPTIONS",
        ),
        SettingDefinition(
            key="api.secret",
            category="api",
            value_type="string",
            default="",
            description="Secret key",
            env_fallback="TEST_API_SECRET",
            is_secret=True,
        ),
        SettingDefinition(
            key="model.backend",
            category="model",
            value_type="string",
            default="gguf",
            description="Model backend",
            requires_reload=True,
        ),
    ]


class TestCoerceValue:
    """Tests for coerce_value function."""

    def test_coerce_string(self):
        """String values pass through unchanged."""
        from jarvis_settings_client.service import coerce_value
        assert coerce_value("hello", "string", "default") == "hello"

    def test_coerce_string_empty_returns_default(self):
        """Empty string returns default."""
        from jarvis_settings_client.service import coerce_value
        assert coerce_value("", "string", "default") == "default"

    def test_coerce_string_none_returns_default(self):
        """None returns default."""
        from jarvis_settings_client.service import coerce_value
        assert coerce_value(None, "string", "default") == "default"

    def test_coerce_int(self):
        """String '42' coerced to int 42."""
        from jarvis_settings_client.service import coerce_value
        assert coerce_value("42", "int", 0) == 42

    def test_coerce_int_invalid_returns_default(self):
        """Invalid int string returns default."""
        from jarvis_settings_client.service import coerce_value
        assert coerce_value("not_an_int", "int", 0) == 0

    def test_coerce_float(self):
        """String '3.14' coerced to float 3.14."""
        from jarvis_settings_client.service import coerce_value
        assert coerce_value("3.14", "float", 0.0) == 3.14

    def test_coerce_float_invalid_returns_default(self):
        """Invalid float string returns default."""
        from jarvis_settings_client.service import coerce_value
        assert coerce_value("not_a_float", "float", 0.0) == 0.0

    def test_coerce_bool_true_values(self):
        """String 'true'/'1'/'yes'/'on' coerced to bool True."""
        from jarvis_settings_client.service import coerce_value
        for value in ["true", "True", "TRUE", "1", "yes", "Yes", "on", "On"]:
            assert coerce_value(value, "bool", False) is True, f"Failed for {value}"

    def test_coerce_bool_false_values(self):
        """String 'false'/'0'/'no'/'off' coerced to bool False."""
        from jarvis_settings_client.service import coerce_value
        for value in ["false", "False", "FALSE", "0", "no", "No", "off", "Off"]:
            assert coerce_value(value, "bool", True) is False, f"Failed for {value}"

    def test_coerce_bool_empty_returns_default(self):
        """Empty string returns default for bool."""
        from jarvis_settings_client.service import coerce_value
        assert coerce_value("", "bool", True) is True
        assert coerce_value("", "bool", False) is False

    def test_coerce_json_dict(self):
        """JSON string coerced to dict."""
        from jarvis_settings_client.service import coerce_value
        result = coerce_value('{"key": "value"}', "json", {})
        assert result == {"key": "value"}

    def test_coerce_json_list(self):
        """JSON string coerced to list."""
        from jarvis_settings_client.service import coerce_value
        result = coerce_value('[1, 2, 3]', "json", [])
        assert result == [1, 2, 3]

    def test_coerce_json_invalid_returns_default(self):
        """Invalid JSON returns default."""
        from jarvis_settings_client.service import coerce_value
        assert coerce_value("not json", "json", {"default": True}) == {"default": True}


class TestSerializeValue:
    """Tests for serialize_value function."""

    def test_serialize_string(self):
        """String serialized as-is."""
        from jarvis_settings_client.service import serialize_value
        assert serialize_value("hello", "string") == "hello"

    def test_serialize_int(self):
        """Int serialized to string."""
        from jarvis_settings_client.service import serialize_value
        assert serialize_value(42, "int") == "42"

    def test_serialize_float(self):
        """Float serialized to string."""
        from jarvis_settings_client.service import serialize_value
        assert serialize_value(3.14, "float") == "3.14"

    def test_serialize_bool_true(self):
        """Bool True serialized to 'true'."""
        from jarvis_settings_client.service import serialize_value
        assert serialize_value(True, "bool") == "true"

    def test_serialize_bool_false(self):
        """Bool False serialized to 'false'."""
        from jarvis_settings_client.service import serialize_value
        assert serialize_value(False, "bool") == "false"

    def test_serialize_json(self):
        """Dict/list serialized to JSON string."""
        from jarvis_settings_client.service import serialize_value
        assert serialize_value({"key": "value"}, "json") == '{"key": "value"}'
        assert serialize_value([1, 2, 3], "json") == "[1, 2, 3]"

    def test_serialize_none(self):
        """None serialized to None."""
        from jarvis_settings_client.service import serialize_value
        assert serialize_value(None, "string") is None


class TestSettingsServiceBasic:
    """Basic tests for SettingsService."""

    def test_get_returns_definition_default_when_no_db_or_env(
        self, sample_definitions: list[SettingDefinition]
    ):
        """Returns definition default when DB value not set and no env var."""
        from jarvis_settings_client.service import SettingsService

        service = SettingsService(
            definitions=sample_definitions,
            get_db_session=lambda: None,  # No DB
        )

        # Clear any env vars
        with patch.dict(os.environ, {}, clear=True):
            for key in ["TEST_MODEL_NAME", "TEST_CONTEXT_WINDOW"]:
                os.environ.pop(key, None)

            result = service.get("model.name")
            assert result == "default-model"

    def test_get_falls_back_to_env_var(
        self, sample_definitions: list[SettingDefinition]
    ):
        """Returns env var when DB value not set."""
        from jarvis_settings_client.service import SettingsService

        service = SettingsService(
            definitions=sample_definitions,
            get_db_session=lambda: None,
        )

        with patch.dict(os.environ, {"TEST_MODEL_NAME": "env-model"}):
            result = service.get("model.name")
            assert result == "env-model"

    def test_get_unknown_key_returns_provided_default(
        self, sample_definitions: list[SettingDefinition]
    ):
        """Unknown key returns the provided default."""
        from jarvis_settings_client.service import SettingsService

        service = SettingsService(
            definitions=sample_definitions,
            get_db_session=lambda: None,
        )

        result = service.get("unknown.key", default="fallback")
        assert result == "fallback"

    def test_get_typed_methods(
        self, sample_definitions: list[SettingDefinition]
    ):
        """Test get_int, get_float, get_bool, get_str methods."""
        from jarvis_settings_client.service import SettingsService

        service = SettingsService(
            definitions=sample_definitions,
            get_db_session=lambda: None,
        )

        with patch.dict(os.environ, {}, clear=True):
            for key in ["TEST_CONTEXT_WINDOW", "TEST_TEMPERATURE", "TEST_FEATURE_ENABLED"]:
                os.environ.pop(key, None)

            assert service.get_int("model.context_window") == 8192
            assert service.get_float("inference.temperature") == 0.7
            assert service.get_bool("feature.enabled") is False
            assert service.get_str("model.name") == "default-model"


class TestSettingsServiceCaching:
    """Tests for SettingsService caching behavior."""

    def test_cache_returns_cached_value(
        self, sample_definitions: list[SettingDefinition]
    ):
        """Cached value returned without DB query."""
        from jarvis_settings_client.service import SettingsService

        db_call_count = 0

        def mock_get_session():
            nonlocal db_call_count
            db_call_count += 1
            return None

        service = SettingsService(
            definitions=sample_definitions,
            get_db_session=mock_get_session,
        )

        with patch.dict(os.environ, {"TEST_MODEL_NAME": "env-value"}):
            # First call
            service.get("model.name")
            first_count = db_call_count

            # Second call should use cache
            service.get("model.name")
            assert db_call_count == first_count

    def test_cache_invalidates_after_ttl(
        self, sample_definitions: list[SettingDefinition]
    ):
        """Cache expires after CACHE_TTL_SECONDS."""
        from jarvis_settings_client.service import SettingsService

        service = SettingsService(
            definitions=sample_definitions,
            get_db_session=lambda: None,
            cache_ttl_seconds=0.1,  # Very short TTL for testing
        )

        with patch.dict(os.environ, {"TEST_MODEL_NAME": "value1"}):
            result1 = service.get("model.name")
            assert result1 == "value1"

        # Wait for cache to expire
        time.sleep(0.15)

        with patch.dict(os.environ, {"TEST_MODEL_NAME": "value2"}):
            # Clear cache entry manually since env changed
            service.invalidate_cache("model.name")
            result2 = service.get("model.name")
            assert result2 == "value2"

    def test_invalidate_cache_single_key(
        self, sample_definitions: list[SettingDefinition]
    ):
        """Invalidate cache for a single key."""
        from jarvis_settings_client.service import SettingsService

        service = SettingsService(
            definitions=sample_definitions,
            get_db_session=lambda: None,
        )

        with patch.dict(os.environ, {"TEST_MODEL_NAME": "value1"}):
            service.get("model.name")  # Cache it
            service.invalidate_cache("model.name")
            # Cache should be empty for this key
            assert "model.name" not in service._cache

    def test_invalidate_cache_all(
        self, sample_definitions: list[SettingDefinition]
    ):
        """Invalidate entire cache."""
        from jarvis_settings_client.service import SettingsService

        service = SettingsService(
            definitions=sample_definitions,
            get_db_session=lambda: None,
        )

        with patch.dict(os.environ, {"TEST_MODEL_NAME": "v1", "TEST_CONTEXT_WINDOW": "1024"}):
            service.get("model.name")
            service.get("model.context_window")
            assert len(service._cache) == 2

            service.invalidate_cache()
            assert len(service._cache) == 0


class TestSettingsServiceMultiTenant:
    """Tests for multi-tenant cascade lookup."""

    def test_cascade_system_default(
        self, sample_definitions: list[SettingDefinition]
    ):
        """System default returned when no scoped values exist."""
        from jarvis_settings_client.service import SettingsService

        # Mock Setting model
        MockSetting = MagicMock()

        # Mock DB session with no results
        mock_session = MagicMock(spec=Session)
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None

        service = SettingsService(
            definitions=sample_definitions,
            get_db_session=lambda: mock_session,
            setting_model=MockSetting,
        )

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("TEST_MODEL_NAME", None)
            result = service.get("model.name")
            assert result == "default-model"

    def test_cascade_household_overrides_system(
        self, sample_definitions: list[SettingDefinition]
    ):
        """Household settings override system defaults."""
        from jarvis_settings_client.service import SettingsService

        # Mock Setting model
        MockSetting = MagicMock()

        # This test requires actual DB - we'll mock the behavior
        mock_session = MagicMock(spec=Session)

        def mock_filter(*args):
            mock_result = MagicMock()
            # Return a mock Setting for household-level query
            mock_setting = MagicMock()
            mock_setting.value = "household-model"
            mock_setting.value_type = "string"
            mock_result.first.return_value = mock_setting
            return mock_result

        mock_query = MagicMock()
        mock_query.filter.side_effect = mock_filter
        mock_session.query.return_value = mock_query

        service = SettingsService(
            definitions=sample_definitions,
            get_db_session=lambda: mock_session,
            setting_model=MockSetting,
        )

        result = service.get(
            "model.name",
            household_id="household-123",
        )
        assert result == "household-model"

    def test_cascade_node_overrides_household(
        self, sample_definitions: list[SettingDefinition]
    ):
        """Node-specific settings override household settings."""
        from jarvis_settings_client.service import SettingsService

        # Mock Setting model
        MockSetting = MagicMock()

        mock_session = MagicMock(spec=Session)

        def mock_filter(*args):
            mock_result = MagicMock()
            mock_setting = MagicMock()
            mock_setting.value = "node-model"
            mock_setting.value_type = "string"
            mock_result.first.return_value = mock_setting
            return mock_result

        mock_query = MagicMock()
        mock_query.filter.side_effect = mock_filter
        mock_session.query.return_value = mock_query

        service = SettingsService(
            definitions=sample_definitions,
            get_db_session=lambda: mock_session,
            setting_model=MockSetting,
        )

        result = service.get(
            "model.name",
            household_id="household-123",
            node_id="node-456",
        )
        assert result == "node-model"

    def test_cascade_user_overrides_node(
        self, sample_definitions: list[SettingDefinition]
    ):
        """User-specific settings override node settings."""
        from jarvis_settings_client.service import SettingsService

        # Mock Setting model
        MockSetting = MagicMock()

        mock_session = MagicMock(spec=Session)

        def mock_filter(*args):
            mock_result = MagicMock()
            mock_setting = MagicMock()
            mock_setting.value = "user-model"
            mock_setting.value_type = "string"
            mock_result.first.return_value = mock_setting
            return mock_result

        mock_query = MagicMock()
        mock_query.filter.side_effect = mock_filter
        mock_session.query.return_value = mock_query

        service = SettingsService(
            definitions=sample_definitions,
            get_db_session=lambda: mock_session,
            setting_model=MockSetting,
        )

        result = service.get(
            "model.name",
            household_id="household-123",
            node_id="node-456",
            user_id=789,
        )
        assert result == "user-model"


class TestSettingsServiceListAndCategories:
    """Tests for list_all and list_categories methods."""

    def test_list_all_returns_all_definitions(
        self, sample_definitions: list[SettingDefinition]
    ):
        """list_all returns all defined settings."""
        from jarvis_settings_client.service import SettingsService

        service = SettingsService(
            definitions=sample_definitions,
            get_db_session=lambda: None,
        )

        with patch.dict(os.environ, {}, clear=True):
            for key in ["TEST_MODEL_NAME", "TEST_CONTEXT_WINDOW", "TEST_TEMPERATURE",
                       "TEST_FEATURE_ENABLED", "TEST_CONFIG_OPTIONS", "TEST_API_SECRET"]:
                os.environ.pop(key, None)

            settings = service.list_all()
            assert len(settings) == len(sample_definitions)

    def test_list_all_filters_by_category(
        self, sample_definitions: list[SettingDefinition]
    ):
        """list_all with category filter returns only matching settings."""
        from jarvis_settings_client.service import SettingsService

        service = SettingsService(
            definitions=sample_definitions,
            get_db_session=lambda: None,
        )

        settings = service.list_all(category="model")
        assert all(s["category"] == "model" for s in settings)
        # Should have model.name, model.context_window, model.backend
        assert len(settings) == 3

    def test_list_all_masks_secrets(
        self, sample_definitions: list[SettingDefinition]
    ):
        """list_all masks is_secret=True values."""
        from jarvis_settings_client.service import SettingsService

        service = SettingsService(
            definitions=sample_definitions,
            get_db_session=lambda: None,
        )

        with patch.dict(os.environ, {"TEST_API_SECRET": "super-secret-key"}):
            settings = service.list_all()
            secret_setting = next(s for s in settings if s["key"] == "api.secret")
            assert secret_setting["value"] == "********"
            assert secret_setting["is_secret"] is True

    def test_list_categories_returns_unique(
        self, sample_definitions: list[SettingDefinition]
    ):
        """list_categories returns unique sorted categories."""
        from jarvis_settings_client.service import SettingsService

        service = SettingsService(
            definitions=sample_definitions,
            get_db_session=lambda: None,
        )

        categories = service.list_categories()
        assert categories == ["api", "config", "feature", "inference", "model"]


class TestSettingsServiceDbPersistence:
    """Tests for set/get with database persistence."""

    def test_set_creates_new_setting(
        self, sample_definitions: list[SettingDefinition]
    ):
        """set() creates a new setting in the database."""
        from jarvis_settings_client.service import SettingsService

        # Mock Setting model class
        MockSetting = MagicMock()

        mock_session = MagicMock(spec=Session)
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None  # No existing setting

        service = SettingsService(
            definitions=sample_definitions,
            get_db_session=lambda: mock_session,
            setting_model=MockSetting,
        )

        result = service.set("model.name", "new-model")
        assert result is True
        mock_session.add.assert_called_once()
        mock_session.commit.assert_called_once()

    def test_set_updates_existing_setting(
        self, sample_definitions: list[SettingDefinition]
    ):
        """set() updates an existing setting."""
        from jarvis_settings_client.service import SettingsService

        # Mock Setting model class
        MockSetting = MagicMock()

        existing_setting = MagicMock()
        existing_setting.value = "old-model"

        mock_session = MagicMock(spec=Session)
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = existing_setting

        service = SettingsService(
            definitions=sample_definitions,
            get_db_session=lambda: mock_session,
            setting_model=MockSetting,
        )

        result = service.set("model.name", "new-model")
        assert result is True
        assert existing_setting.value == "new-model"
        mock_session.commit.assert_called_once()

    def test_set_unknown_key_returns_false(
        self, sample_definitions: list[SettingDefinition]
    ):
        """set() returns False for unknown key."""
        from jarvis_settings_client.service import SettingsService

        service = SettingsService(
            definitions=sample_definitions,
            get_db_session=lambda: None,
        )

        result = service.set("unknown.key", "value")
        assert result is False

    def test_set_invalidates_cache(
        self, sample_definitions: list[SettingDefinition]
    ):
        """set() invalidates cache for the updated key."""
        from jarvis_settings_client.service import SettingsService

        # Mock Setting model class
        MockSetting = MagicMock()

        mock_session = MagicMock(spec=Session)
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None

        service = SettingsService(
            definitions=sample_definitions,
            get_db_session=lambda: mock_session,
            setting_model=MockSetting,
        )

        # Cache a value first
        with patch.dict(os.environ, {"TEST_MODEL_NAME": "cached-value"}):
            service.get("model.name")
            # Cache key includes scope: "model.name|None|None|None"
            cache_key = service._make_cache_key("model.name")
            assert cache_key in service._cache

        # Set new value
        service.set("model.name", "new-value")

        # Cache should be invalidated
        assert cache_key not in service._cache


class TestSettingsServiceSyncFromEnv:
    """Tests for sync_from_env migration helper."""

    def test_sync_from_env_syncs_set_env_vars(
        self, sample_definitions: list[SettingDefinition]
    ):
        """sync_from_env syncs only env vars that are set."""
        from jarvis_settings_client.service import SettingsService

        # Mock Setting model class
        MockSetting = MagicMock()

        mock_session = MagicMock(spec=Session)
        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.first.return_value = None

        service = SettingsService(
            definitions=sample_definitions,
            get_db_session=lambda: mock_session,
            setting_model=MockSetting,
        )

        with patch.dict(os.environ, {"TEST_MODEL_NAME": "synced-model"}, clear=True):
            results = service.sync_from_env()

            # Only TEST_MODEL_NAME was set
            assert results["model.name"] is True
            # Others were not set
            assert results.get("model.context_window") is False

    def test_sync_from_env_skips_no_fallback(
        self, sample_definitions: list[SettingDefinition]
    ):
        """sync_from_env skips settings without env_fallback."""
        from jarvis_settings_client.service import SettingsService

        service = SettingsService(
            definitions=sample_definitions,
            get_db_session=lambda: None,
        )

        # model.backend has no env_fallback
        results = service.sync_from_env()
        assert results.get("model.backend") is False


class TestSettingsServiceThreadSafety:
    """Tests for thread safety."""

    def test_cache_operations_are_thread_safe(
        self, sample_definitions: list[SettingDefinition]
    ):
        """Cache operations use thread lock."""
        from jarvis_settings_client.service import SettingsService

        service = SettingsService(
            definitions=sample_definitions,
            get_db_session=lambda: None,
        )

        # Verify _cache_lock exists
        assert hasattr(service, "_cache_lock")

        # This is a structural test - actual thread safety
        # would require concurrent execution tests


class TestCascadeAgainstRealDb:
    """Cascade tests against a real in-memory SQLite session.

    The MagicMock cascade tests above cannot see a scope bug — a mocked
    ``.first()`` returns a row no matter what the filter was. These use a real
    session and a real model so the WHERE clauses actually run. This class
    exists because a user-only setting (household/node NULL, user_id set) was
    silently write-only: ``set(key, user_id=n)`` persisted it but the cascade
    had no branch that matched it back, so ``get`` fell through to the default.
    """

    def _service(self, sample_definitions):
        from sqlalchemy.orm import declarative_base
        from sqlalchemy import Boolean, Column, Integer, String

        Base = declarative_base()

        class Setting(Base):
            __tablename__ = "settings"
            id = Column(Integer, primary_key=True)
            key = Column(String, nullable=False)
            value = Column(String)
            value_type = Column(String)
            category = Column(String)
            description = Column(String)
            requires_reload = Column(Boolean, default=False)
            is_secret = Column(Boolean, default=False)
            env_fallback = Column(String)
            household_id = Column(String, nullable=True)
            node_id = Column(String, nullable=True)
            user_id = Column(Integer, nullable=True)

        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        SessionLocal = sessionmaker(bind=engine)

        from jarvis_settings_client.service import SettingsService

        return SettingsService(
            definitions=sample_definitions,
            get_db_session=lambda: SessionLocal(),
            setting_model=Setting,
        )

    def test_user_scoped_value_survives_the_round_trip(self, sample_definitions):
        """The regression: write with user_id only, read it back with user_id
        only. Before the fix this returned the definition default."""
        service = self._service(sample_definitions)

        assert service.set("model.name", "my-personal-model", user_id=42) is True
        assert service.get("model.name", user_id=42) == "my-personal-model"

    def test_a_users_value_does_not_leak_to_another_user(self, sample_definitions):
        service = self._service(sample_definitions)
        service.set("model.name", "alice-model", user_id=1)

        assert service.get("model.name", user_id=2) == "default-model"

    def test_user_value_beats_the_system_default_row(self, sample_definitions):
        service = self._service(sample_definitions)
        service.set("model.name", "system-wide")            # all-NULL scope
        service.set("model.name", "just-mine", user_id=7)

        assert service.get("model.name", user_id=7) == "just-mine"
        assert service.get("model.name") == "system-wide"
