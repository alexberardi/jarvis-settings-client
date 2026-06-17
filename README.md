# jarvis-settings-client

A shared settings library for Jarvis microservices. It stores runtime
configuration in a database (with environment-variable fallback), provides
thread-safe cached reads with typed getters, supports multi-tenant
(household / node / user) cascade lookups, and ships a ready-to-mount FastAPI
router for settings CRUD.

## Install

```bash
pip install -e .

# with dev/test extras
pip install -e ".[dev]"
```

Requires Python 3.10+.

## Usage

Define your settings, wire the service to your SQLAlchemy session and model,
then read and write values:

```python
from jarvis_settings_client import SettingDefinition, SettingsService
from your_db import get_db, Setting  # your SQLAlchemy session factory + model

SETTINGS = [
    SettingDefinition(
        key="model.name",
        category="model",
        value_type="string",          # string, int, float, bool, json
        default="default-model",
        description="Model name",
        env_fallback="MODEL_NAME",    # optional env-var fallback
    ),
    SettingDefinition(
        key="model.context_window",
        category="model",
        value_type="int",
        default=8192,
        env_fallback="CONTEXT_WINDOW",
    ),
]

service = SettingsService(
    definitions=SETTINGS,
    get_db_session=get_db,
    setting_model=Setting,
)

# Read (cached, with typed getters)
name = service.get_str("model.name")
window = service.get_int("model.context_window")

# Multi-tenant scoped read (first match wins:
# user -> node -> household -> system default)
name = service.get("model.name", household_id="h123", node_id="n456", user_id=789)

# Write
service.set("model.name", "new-model")
service.set("model.name", "household-model", household_id="h123")
```

Mount the optional API router:

```python
from fastapi import FastAPI
from jarvis_settings_client import create_settings_router

app = FastAPI()
router = create_settings_router(service=service, auth_dependency=require_app_client)
app.include_router(router, prefix="/settings")
```

This exposes `GET /settings`, `GET /settings/categories`,
`GET/PUT /settings/{key}`, `POST /settings/sync-from-env`, and
`POST /settings/invalidate-cache`, with `?category=`, `?household_id=`,
`?node_id=`, and `?user_id=` query parameters.

## Features

- Thread-safe caching (60s TTL by default)
- Environment-variable fallback when a DB value is unset
- Automatic type coercion (string, int, float, bool, json)
- Secret masking for `is_secret=True` settings
- Multi-tenant cascade lookup by household / node / user

## Testing

```bash
pytest
pytest --cov=jarvis_settings_client --cov-report=term-missing
```

## License

Apache License, Version 2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
