"""Tests for jarvis_settings_client.types module."""

import pytest

from jarvis_settings_client.types import SettingDefinition, SettingValue


class TestSettingDefinition:
    """Tests for SettingDefinition dataclass."""

    def test_required_fields(self):
        """Test creating definition with required fields."""
        definition = SettingDefinition(
            key="test.key",
            category="test",
            value_type="string",
            default="default_value",
            description="A test setting",
        )
        assert definition.key == "test.key"
        assert definition.category == "test"
        assert definition.value_type == "string"
        assert definition.default == "default_value"
        assert definition.description == "A test setting"

    def test_optional_fields_have_defaults(self):
        """Test that optional fields have sensible defaults."""
        definition = SettingDefinition(
            key="test.key",
            category="test",
            value_type="string",
            default="value",
            description="Test",
        )
        assert definition.env_fallback is None
        assert definition.requires_reload is False
        assert definition.is_secret is False

    def test_env_fallback_can_be_set(self):
        """Test setting env_fallback."""
        definition = SettingDefinition(
            key="test.key",
            category="test",
            value_type="int",
            default=42,
            description="Test",
            env_fallback="TEST_KEY_ENV",
        )
        assert definition.env_fallback == "TEST_KEY_ENV"

    def test_requires_reload_can_be_set(self):
        """Test setting requires_reload."""
        definition = SettingDefinition(
            key="test.key",
            category="test",
            value_type="string",
            default="value",
            description="Test",
            requires_reload=True,
        )
        assert definition.requires_reload is True

    def test_is_secret_can_be_set(self):
        """Test setting is_secret."""
        definition = SettingDefinition(
            key="api.secret_key",
            category="api",
            value_type="string",
            default="",
            description="Secret API key",
            is_secret=True,
        )
        assert definition.is_secret is True

    def test_all_value_types_accepted(self):
        """Test that all supported value types can be used."""
        for value_type in ["string", "int", "float", "bool", "json"]:
            definition = SettingDefinition(
                key=f"test.{value_type}",
                category="test",
                value_type=value_type,
                default=None,
                description=f"Test {value_type}",
            )
            assert definition.value_type == value_type


class TestSettingValue:
    """Tests for SettingValue dataclass."""

    def test_required_fields(self):
        """Test creating SettingValue with required fields."""
        value = SettingValue(
            value="test_value",
            value_type="string",
            requires_reload=False,
            is_secret=False,
            env_fallback=None,
            from_db=True,
            cached_at=1234567890.0,
        )
        assert value.value == "test_value"
        assert value.value_type == "string"
        assert value.requires_reload is False
        assert value.is_secret is False
        assert value.env_fallback is None
        assert value.from_db is True
        assert value.cached_at == 1234567890.0

    def test_value_can_be_any_type(self):
        """Test that value field accepts any type."""
        # String
        v1 = SettingValue(
            value="test", value_type="string", requires_reload=False,
            is_secret=False, env_fallback=None, from_db=True, cached_at=0.0
        )
        assert v1.value == "test"

        # Int
        v2 = SettingValue(
            value=42, value_type="int", requires_reload=False,
            is_secret=False, env_fallback=None, from_db=True, cached_at=0.0
        )
        assert v2.value == 42

        # Float
        v3 = SettingValue(
            value=3.14, value_type="float", requires_reload=False,
            is_secret=False, env_fallback=None, from_db=True, cached_at=0.0
        )
        assert v3.value == 3.14

        # Bool
        v4 = SettingValue(
            value=True, value_type="bool", requires_reload=False,
            is_secret=False, env_fallback=None, from_db=True, cached_at=0.0
        )
        assert v4.value is True

        # JSON (dict)
        v5 = SettingValue(
            value={"key": "value"}, value_type="json", requires_reload=False,
            is_secret=False, env_fallback=None, from_db=True, cached_at=0.0
        )
        assert v5.value == {"key": "value"}

        # JSON (list)
        v6 = SettingValue(
            value=[1, 2, 3], value_type="json", requires_reload=False,
            is_secret=False, env_fallback=None, from_db=True, cached_at=0.0
        )
        assert v6.value == [1, 2, 3]

    def test_from_db_distinguishes_source(self):
        """Test that from_db correctly indicates value source."""
        db_value = SettingValue(
            value="from_db", value_type="string", requires_reload=False,
            is_secret=False, env_fallback=None, from_db=True, cached_at=0.0
        )
        assert db_value.from_db is True

        env_value = SettingValue(
            value="from_env", value_type="string", requires_reload=False,
            is_secret=False, env_fallback="TEST_VAR", from_db=False, cached_at=0.0
        )
        assert env_value.from_db is False
