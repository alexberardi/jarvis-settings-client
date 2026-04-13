"""Type definitions for jarvis-settings-client.

Defines the core data structures used throughout the settings system.
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class SettingDefinition:
    """Definition for a setting with its default value and metadata.

    This defines what settings exist and their properties. Each service
    creates a list of SettingDefinitions to describe its configurable settings.

    Attributes:
        key: Unique setting key using dot notation (e.g., "model.main.name")
        category: Grouping category (e.g., "model", "inference", "logging")
        value_type: Type of the value: "string", "int", "float", "bool", "json"
        default: Default value when not set in DB or env
        description: Human-readable description of the setting
        env_fallback: Environment variable name to check if DB value not set
        requires_reload: Whether changing this setting requires service restart
        is_secret: Whether to mask this value in API responses
    """

    key: str
    category: str
    value_type: str
    default: Any
    description: str
    env_fallback: str | None = None
    requires_reload: bool = False
    is_secret: bool = False
    options: list[Any] | None = None


@dataclass
class SettingValue:
    """A cached setting value with metadata.

    Represents a resolved setting value after looking up from DB, env, or default.

    Attributes:
        value: The resolved value (already coerced to correct type)
        value_type: Type of the value (from SettingDefinition)
        requires_reload: Whether changing this setting requires restart
        is_secret: Whether this is a secret value
        env_fallback: Environment variable name (if defined)
        from_db: True if value came from database, False if from env/default
        cached_at: Unix timestamp when this value was cached
    """

    value: Any
    value_type: str
    requires_reload: bool
    is_secret: bool
    env_fallback: str | None
    from_db: bool
    cached_at: float
