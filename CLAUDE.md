# jarvis-settings-client

Shared settings library for jarvis microservices with multi-tenant support, caching, and environment variable fallback.

## Quick Reference

```bash
# Install
pip install -e .

# Test
pytest

# Coverage
pytest --cov=jarvis_settings_client --cov-report=term-missing
```

## Usage

### 1. Define Settings

```python
from jarvis_settings_client import SettingDefinition

SETTINGS = [
    SettingDefinition(
        key="model.name",
        category="model",
        value_type="string",  # string, int, float, bool, json
        default="default-model",
        description="Model name",
        env_fallback="MODEL_NAME",  # Optional env var fallback
        requires_reload=False,  # True if change needs service restart
        is_secret=False,  # True to mask in API responses
    ),
    SettingDefinition(
        key="model.context_window",
        category="model",
        value_type="int",
        default=8192,
        description="Context window size",
        env_fallback="CONTEXT_WINDOW",
    ),
]
```

### 2. Create Settings Service

```python
from jarvis_settings_client import SettingsService
from your_db import get_db, Setting  # Your SQLAlchemy session and model

service = SettingsService(
    definitions=SETTINGS,
    get_db_session=get_db,
    setting_model=Setting,  # SQLAlchemy model
)
```

### 3. Use Settings

```python
# Get a setting (with caching)
model_name = service.get("model.name")

# Typed getters
context_window = service.get_int("model.context_window")
temperature = service.get_float("inference.temperature")
enabled = service.get_bool("feature.enabled")
name = service.get_str("model.name")

# Multi-tenant scoped lookup
model_name = service.get(
    "model.name",
    household_id="h123",
    node_id="n456",
    user_id=789,
)

# Set a setting
service.set("model.name", "new-model")

# Set with scope
service.set("model.name", "household-model", household_id="h123")
```

### 4. Add API Routes

```python
from fastapi import FastAPI
from jarvis_settings_client import create_settings_router
from your_auth import require_app_client  # Your auth dependency

app = FastAPI()

router = create_settings_router(
    service=service,
    auth_dependency=require_app_client,
)
app.include_router(router, prefix="/settings")
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /settings | List all settings |
| GET | /settings/categories | List unique categories |
| GET | /settings/{key} | Get single setting |
| PUT | /settings/{key} | Update setting |
| POST | /settings/sync-from-env | Migrate env vars to DB |
| POST | /settings/invalidate-cache | Clear cache |

Query parameters: `?category=`, `?household_id=`, `?node_id=`, `?user_id=`

## Multi-Tenant Cascade Lookup

Settings are looked up in this order (first match wins):

1. **User-specific**: `household_id` + `node_id` + `user_id` match
2. **Node-level**: `household_id` + `node_id` match, `user_id` NULL
3. **Household-level**: `household_id` match, `node_id` NULL, `user_id` NULL
4. **System default**: all scope fields NULL

## Database Schema

Services need a `settings` table. Example SQLAlchemy model:

```python
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime
from sqlalchemy.sql import func

class Setting(Base):
    __tablename__ = "settings"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(255), nullable=False, index=True)
    value = Column(Text, nullable=True)  # JSON-encoded
    value_type = Column(String(50), nullable=False)
    category = Column(String(100), nullable=False, index=True)
    description = Column(Text, nullable=True)
    requires_reload = Column(Boolean, default=False)
    is_secret = Column(Boolean, default=False)
    env_fallback = Column(String(255), nullable=True)

    # Multi-tenant scoping
    household_id = Column(String(255), nullable=True, index=True)
    node_id = Column(String(255), nullable=True, index=True)
    user_id = Column(Integer, nullable=True, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
```

## Features

- **Thread-safe caching**: 60s TTL by default
- **Environment fallback**: Falls back to env vars if DB value not set
- **Type coercion**: Automatic conversion from string to target type
- **Secret masking**: `is_secret=True` settings show `********` in API
- **Multi-tenant**: Cascade lookup by household/node/user

## Version

0.1.0
