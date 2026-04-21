"""Load error translations from en.json translations file."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _load_errors() -> dict[str, Any]:
    """Load error translations from en.json."""
    translations_path = Path(__file__).parent.parent / "translations" / "en.json"
    try:
        with open(translations_path, encoding="utf-8") as f:
            data = json.load(f)
            return data.get("errors", {})
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


_ERRORS_CACHE = _load_errors()


class _ErrorCategory:
    """Dynamic error category that loads strings from translations."""

    def __init__(self, category: str):
        self._category = category
        self._strings = _ERRORS_CACHE.get(category, {})

    def __getattr__(self, name: str) -> str:
        """Get error string by attribute name."""
        if name.startswith("_"):
            return object.__getattribute__(self, name)
        value = self._strings.get(name, f"[Missing translation: {self._category}.{name}]")
        return str(value)


# Create error category instances
ErrorsGeneral = _ErrorCategory("general")
ErrorsFileNotFound = _ErrorCategory("file_not_found")
ErrorsMQTTClient = _ErrorCategory("mqtt_client")
ErrorsAPIParsing = _ErrorCategory("api_parsing")
ErrorsDataParsing = _ErrorCategory("data_parsing")
ErrorsGcodeParsing = _ErrorCategory("gcode_parsing")
ErrorsAuth = _ErrorCategory("auth")
ErrorsAuthTokenExpired = _ErrorCategory("auth_token_expired")
ErrorsInvalidValue = _ErrorCategory("invalid_value")
ErrorsLoadingProps = _ErrorCategory("loading_props")
ErrorsCloudUpload = _ErrorCategory("cloud_upload")
ErrorsMQTTUpdate = _ErrorCategory("mqtt_update")
ErrorsSystem = _ErrorCategory("system")
