"""Settings service with caching, environment variable fallback, and multi-tenant support.

This service provides runtime configuration that can be modified without
restarting the application. Settings are stored in the database with
fallback to environment variables for backward compatibility.

Multi-tenant cascade lookup order:
1. User-specific: household_id + node_id + user_id match
2. Node-specific: household_id + node_id match, user_id NULL
3. Household-level: household_id match, node_id NULL, user_id NULL
4. System default: all scope fields NULL
"""

import json
import logging
import os
import threading
import time
from typing import Any, Callable

from sqlalchemy.orm import Session

from jarvis_settings_client.types import SettingDefinition, SettingValue

logger = logging.getLogger(__name__)


def coerce_value(raw: str | None, value_type: str, default: Any) -> Any:
    """Coerce a string value to the appropriate type.

    Args:
        raw: Raw string value from database or environment
        value_type: Target type ("string", "int", "float", "bool", "json")
        default: Default value to return if coercion fails or raw is empty

    Returns:
        The coerced value, or default if coercion fails
    """
    if raw is None or raw == "":
        return default

    try:
        if value_type == "string":
            return raw
        elif value_type == "int":
            return int(raw)
        elif value_type == "float":
            return float(raw)
        elif value_type == "bool":
            return raw.lower() in ("true", "1", "yes", "on")
        elif value_type == "json":
            return json.loads(raw)
        else:
            return raw
    except (ValueError, json.JSONDecodeError) as e:
        logger.warning(f"Failed to coerce value '{raw}' to {value_type}: {e}")
        return default


def serialize_value(value: Any, value_type: str) -> str | None:
    """Serialize a value to string for database storage.

    Args:
        value: Value to serialize
        value_type: Type hint for serialization

    Returns:
        Serialized string, or None if value is None
    """
    if value is None:
        return None

    if value_type == "json":
        return json.dumps(value)
    elif value_type == "bool":
        return "true" if value else "false"
    else:
        return str(value)


class SettingsService:
    """Thread-safe settings service with caching and multi-tenant support.

    This service manages settings for a jarvis microservice. It supports:
    - Database persistence with SQLAlchemy
    - Environment variable fallback
    - In-memory caching with TTL
    - Multi-tenant cascade lookup (user > node > household > system)
    - Thread-safe operations

    Usage:
        from jarvis_settings_client import SettingsService, SettingDefinition

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

        service = SettingsService(
            definitions=SETTINGS,
            get_db_session=get_db,
        )

        # Get a setting
        model_name = service.get("model.name")

        # Get with scope (multi-tenant)
        model_name = service.get("model.name", household_id="h123", node_id="n456")

        # Set a setting
        service.set("model.name", "new-model")
    """

    DEFAULT_CACHE_TTL_SECONDS = 60

    def __init__(
        self,
        definitions: list[SettingDefinition],
        get_db_session: Callable[[], Session | None],
        setting_model: Any = None,
        cache_ttl_seconds: float = DEFAULT_CACHE_TTL_SECONDS,
    ) -> None:
        """Initialize the settings service.

        Args:
            definitions: List of SettingDefinition objects describing settings
            get_db_session: Callable that returns a SQLAlchemy Session (or None)
            setting_model: SQLAlchemy model class for the settings table
            cache_ttl_seconds: How long to cache values (default 60s)
        """
        self._definitions: dict[str, SettingDefinition] = {
            d.key: d for d in definitions
        }
        self._get_db_session = get_db_session
        self._setting_model = setting_model
        self._cache_ttl_seconds = cache_ttl_seconds
        self._cache: dict[str, SettingValue] = {}
        self._cache_lock = threading.Lock()

        logger.info(
            f"SettingsService initialized with {len(self._definitions)} settings definitions"
        )

    def _is_cache_valid(self, cache_key: str) -> bool:
        """Check if a cached value is still valid."""
        if cache_key not in self._cache:
            return False
        cached = self._cache[cache_key]
        return (time.time() - cached.cached_at) < self._cache_ttl_seconds

    def _make_cache_key(
        self,
        key: str,
        household_id: str | None = None,
        node_id: str | None = None,
        user_id: int | None = None,
    ) -> str:
        """Create a cache key that includes scope parameters."""
        return f"{key}|{household_id}|{node_id}|{user_id}"

    def _query_db_cascade(
        self,
        key: str,
        household_id: str | None,
        node_id: str | None,
        user_id: int | None,
        db: Session,
    ) -> tuple[str | None, str | None, bool]:
        """Query database with cascade lookup.

        Returns:
            Tuple of (value, value_type, from_db)
        """
        if self._setting_model is None:
            return None, None, False

        Setting = self._setting_model

        # Level 1: User-specific (requires all three)
        if household_id is not None and node_id is not None and user_id is not None:
            setting = (
                db.query(Setting)
                .filter(
                    Setting.key == key,
                    Setting.household_id == household_id,
                    Setting.node_id == node_id,
                    Setting.user_id == user_id,
                )
                .first()
            )
            if setting:
                return setting.value, setting.value_type, True

        # Level 1b: User-only (a personal setting with no household/node
        # context). set() writes such a row with household_id and node_id
        # NULL and user_id set; without this branch that row is unreachable
        # and get() falls straight through to the system default — user-scoped
        # settings were effectively write-only. A user's own value takes
        # precedence over the node/household/system defaults below, which is
        # the point of scoping it to the user.
        if user_id is not None:
            setting = (
                db.query(Setting)
                .filter(
                    Setting.key == key,
                    Setting.household_id.is_(None),
                    Setting.node_id.is_(None),
                    Setting.user_id == user_id,
                )
                .first()
            )
            if setting:
                return setting.value, setting.value_type, True

        # Level 2: Node-specific (requires household_id and node_id)
        if household_id is not None and node_id is not None:
            setting = (
                db.query(Setting)
                .filter(
                    Setting.key == key,
                    Setting.household_id == household_id,
                    Setting.node_id == node_id,
                    Setting.user_id.is_(None),
                )
                .first()
            )
            if setting:
                return setting.value, setting.value_type, True

        # Level 3: Household-level (requires household_id)
        if household_id is not None:
            setting = (
                db.query(Setting)
                .filter(
                    Setting.key == key,
                    Setting.household_id == household_id,
                    Setting.node_id.is_(None),
                    Setting.user_id.is_(None),
                )
                .first()
            )
            if setting:
                return setting.value, setting.value_type, True

        # Level 4: System default (all NULL)
        setting = (
            db.query(Setting)
            .filter(
                Setting.key == key,
                Setting.household_id.is_(None),
                Setting.node_id.is_(None),
                Setting.user_id.is_(None),
            )
            .first()
        )
        if setting:
            return setting.value, setting.value_type, True

        return None, None, False

    def get(
        self,
        key: str,
        default: Any = None,
        household_id: str | None = None,
        node_id: str | None = None,
        user_id: int | None = None,
    ) -> Any:
        """Get a setting value with caching and cascade lookup.

        Order of precedence:
        1. Cached value (if not expired)
        2. Database value (with cascade: user > node > household > system)
        3. Environment variable fallback
        4. Definition default
        5. Provided default

        Args:
            key: Setting key (e.g., "model.name")
            default: Default value if setting not found
            household_id: Optional household scope
            node_id: Optional node scope
            user_id: Optional user scope

        Returns:
            The setting value
        """
        # Check for unknown key
        definition = self._definitions.get(key)
        if definition is None:
            logger.debug(f"Unknown setting key: {key}")
            return default

        cache_key = self._make_cache_key(key, household_id, node_id, user_id)

        # 1. Check cache
        with self._cache_lock:
            if self._is_cache_valid(cache_key):
                return self._cache[cache_key].value

        # 2. Query database with cascade
        db_value = None
        from_db = False

        try:
            db = self._get_db_session()
            if db is not None:
                try:
                    raw_value, value_type, from_db = self._query_db_cascade(
                        key, household_id, node_id, user_id, db
                    )
                    if from_db and raw_value is not None:
                        db_value = coerce_value(
                            raw_value,
                            value_type or definition.value_type,
                            definition.default,
                        )
                finally:
                    db.close()
        except Exception as e:
            logger.debug(f"Database unavailable for setting {key}: {e}")

        # 3. Fallback to env var
        if db_value is None and definition.env_fallback:
            env_value = os.getenv(definition.env_fallback)
            if env_value is not None:
                db_value = coerce_value(env_value, definition.value_type, definition.default)

        # 4. Use definition default
        if db_value is None:
            db_value = definition.default

        # Cache the result
        with self._cache_lock:
            self._cache[cache_key] = SettingValue(
                value=db_value,
                value_type=definition.value_type,
                requires_reload=definition.requires_reload,
                is_secret=definition.is_secret,
                env_fallback=definition.env_fallback,
                from_db=from_db,
                cached_at=time.time(),
            )

        return db_value

    def get_typed(self, key: str, value_type: type, default: Any = None) -> Any:
        """Get a setting with explicit type checking."""
        value = self.get(key, default)
        if not isinstance(value, value_type):
            return default
        return value

    def get_int(self, key: str, default: int = 0) -> int:
        """Get an integer setting."""
        return self.get_typed(key, int, default)

    def get_float(self, key: str, default: float = 0.0) -> float:
        """Get a float setting."""
        value = self.get(key, default)
        if isinstance(value, (int, float)):
            return float(value)
        return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        """Get a boolean setting."""
        return self.get_typed(key, bool, default)

    def get_str(self, key: str, default: str = "") -> str:
        """Get a string setting."""
        return self.get_typed(key, str, default)

    def set(
        self,
        key: str,
        value: Any,
        household_id: str | None = None,
        node_id: str | None = None,
        user_id: int | None = None,
    ) -> bool:
        """Set a setting value in the database.

        Args:
            key: Setting key
            value: New value
            household_id: Optional household scope
            node_id: Optional node scope
            user_id: Optional user scope

        Returns:
            True if successful, False otherwise
        """
        definition = self._definitions.get(key)
        if definition is None:
            logger.warning(f"Cannot set unknown setting key: {key}")
            return False

        if self._setting_model is None:
            logger.warning("No setting model configured, cannot persist")
            return False

        try:
            db = self._get_db_session()
            if db is None:
                logger.warning("No database session available")
                return False

            try:
                Setting = self._setting_model

                # Build exact scope filter
                query = db.query(Setting).filter(Setting.key == key)

                if household_id is None:
                    query = query.filter(Setting.household_id.is_(None))
                else:
                    query = query.filter(Setting.household_id == household_id)

                if node_id is None:
                    query = query.filter(Setting.node_id.is_(None))
                else:
                    query = query.filter(Setting.node_id == node_id)

                if user_id is None:
                    query = query.filter(Setting.user_id.is_(None))
                else:
                    query = query.filter(Setting.user_id == user_id)

                existing = query.first()
                serialized = serialize_value(value, definition.value_type)

                if existing:
                    existing.value = serialized
                else:
                    setting = Setting(
                        key=key,
                        value=serialized,
                        value_type=definition.value_type,
                        category=definition.category,
                        description=definition.description,
                        requires_reload=definition.requires_reload,
                        is_secret=definition.is_secret,
                        env_fallback=definition.env_fallback,
                        household_id=household_id,
                        node_id=node_id,
                        user_id=user_id,
                    )
                    db.add(setting)

                db.commit()

                # Invalidate cache for this key (all scopes)
                self._invalidate_key_all_scopes(key)

                logger.info(f"Setting updated: {key}")
                return True
            finally:
                db.close()
        except Exception as e:
            logger.error(f"Failed to set setting {key}: {e}")
            return False

    def _invalidate_key_all_scopes(self, key: str) -> None:
        """Invalidate cache entries for a key across all scopes."""
        with self._cache_lock:
            keys_to_remove = [k for k in self._cache if k.startswith(f"{key}|")]
            for k in keys_to_remove:
                del self._cache[k]

    def invalidate_cache(self, key: str | None = None) -> None:
        """Invalidate cache for a specific key or all keys.

        Args:
            key: Setting key to invalidate, or None to clear all
        """
        with self._cache_lock:
            if key:
                # Invalidate all scopes for this key
                keys_to_remove = [k for k in self._cache if k.startswith(f"{key}|")]
                for k in keys_to_remove:
                    del self._cache[k]
            else:
                self._cache.clear()
        logger.info(f"Cache invalidated: {key or 'all'}")

    def list_all(
        self,
        category: str | None = None,
        household_id: str | None = None,
        node_id: str | None = None,
        user_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """List all settings with their current values.

        Args:
            category: Optional category filter
            household_id: Optional household scope for value lookup
            node_id: Optional node scope for value lookup
            user_id: Optional user scope for value lookup

        Returns:
            List of setting dictionaries with all metadata
        """
        result = []

        # Get all settings from DB for this scope
        db_settings: dict[str, dict[str, Any]] = {}
        try:
            db = self._get_db_session()
            if db is not None and self._setting_model is not None:
                try:
                    Setting = self._setting_model
                    query = db.query(Setting)
                    if category:
                        query = query.filter(Setting.category == category)
                    for setting in query.all():
                        db_settings[setting.key] = {
                            "value": setting.value,
                            "value_type": setting.value_type,
                            "from_db": True,
                        }
                finally:
                    db.close()
        except Exception as e:
            logger.debug(f"Database unavailable for listing settings: {e}")

        # Merge with definitions
        for key, definition in self._definitions.items():
            if category and definition.category != category:
                continue

            # Determine current value
            if key in db_settings:
                raw_value = db_settings[key]["value"]
                current_value = coerce_value(
                    raw_value, definition.value_type, definition.default
                )
                from_db = True
            elif definition.env_fallback:
                env_value = os.getenv(definition.env_fallback)
                if env_value is not None:
                    current_value = coerce_value(
                        env_value, definition.value_type, definition.default
                    )
                    from_db = False
                else:
                    current_value = definition.default
                    from_db = False
            else:
                current_value = definition.default
                from_db = False

            # Mask secrets
            display_value = current_value
            if definition.is_secret and current_value:
                display_value = "********"

            result.append(
                {
                    "key": key,
                    "value": display_value,
                    "value_type": definition.value_type,
                    "category": definition.category,
                    "description": definition.description,
                    "requires_reload": definition.requires_reload,
                    "is_secret": definition.is_secret,
                    "env_fallback": definition.env_fallback,
                    "from_db": from_db,
                    "options": definition.options,
                }
            )

        return sorted(result, key=lambda x: (x["category"], x["key"]))

    def list_categories(self) -> list[str]:
        """List all unique categories.

        Returns:
            Sorted list of unique category names
        """
        categories = set(d.category for d in self._definitions.values())
        return sorted(categories)

    def sync_from_env(self) -> dict[str, bool]:
        """Sync all settings from environment variables to database.

        This is a one-time migration helper. Only syncs settings that
        have an env_fallback defined and where the env var is set.

        Returns:
            Dict mapping setting keys to whether they were synced
        """
        results = {}
        for key, definition in self._definitions.items():
            if not definition.env_fallback:
                results[key] = False
                continue

            env_value = os.getenv(definition.env_fallback)
            if env_value is None:
                results[key] = False
                continue

            # Coerce and set
            value = coerce_value(env_value, definition.value_type, definition.default)
            results[key] = self.set(key, value)

        synced_count = sum(1 for v in results.values() if v)
        logger.info(f"Synced {synced_count} settings from environment variables")
        return results

    @property
    def definitions(self) -> dict[str, SettingDefinition]:
        """Get the definitions dictionary (read-only access)."""
        return self._definitions
