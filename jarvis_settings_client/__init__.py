"""jarvis-settings-client: Shared settings library for jarvis microservices.

Provides:
- SettingDefinition: Define settings with types, defaults, and env fallbacks
- SettingValue: Cached setting values with metadata
- SettingsService: Thread-safe settings access with caching and multi-tenant support
- create_settings_router: FastAPI router factory for settings endpoints

Usage:
    from jarvis_settings_client import (
        SettingDefinition,
        SettingsService,
        create_settings_router,
    )

    # Define your settings
    SETTINGS = [
        SettingDefinition(
            key="model.name",
            category="model",
            value_type="string",
            default="default-model",
            description="Model name",
            env_fallback="MODEL_NAME",
        ),
    ]

    # Create service
    settings = SettingsService(
        definitions=SETTINGS,
        get_db_session=get_db,
    )

    # Use settings
    model_name = settings.get("model.name")
"""

from jarvis_settings_client.types import SettingDefinition, SettingValue
from jarvis_settings_client.service import SettingsService, coerce_value, serialize_value
from jarvis_settings_client.routes import create_settings_router

__all__ = [
    "SettingDefinition",
    "SettingValue",
    "SettingsService",
    "coerce_value",
    "serialize_value",
    "create_settings_router",
]
__version__ = "0.1.0"
