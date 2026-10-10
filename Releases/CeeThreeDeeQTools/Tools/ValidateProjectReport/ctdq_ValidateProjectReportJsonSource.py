import json
from collections.abc import Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtNetwork import QNetworkRequest
from qgis.core import QgsBlockingNetworkRequest


REQUEST_TIMEOUT_MS = 20000


class JsonSourceError(ValueError):
    """Raised when a JSON validation source cannot be read or parsed."""


class ValidateProjectReportJsonSource:
    """Fetches and normalizes JSON record sources for project-report validation."""

    @staticmethod
    def validate_url(url):
        url = (url or "").strip()
        try:
            parsed = urlsplit(url)
            valid = parsed.scheme.lower() in ("http", "https") and bool(parsed.hostname)
            parsed.port
        except ValueError:
            valid = False
        if not valid:
            raise JsonSourceError("Enter a valid HTTP or HTTPS URL.")
        if parsed.username or parsed.password:
            raise JsonSourceError(
                "Credentials must be selected through a QGIS authentication config, not embedded in the URL."
            )
        return url

    @staticmethod
    def redact_url_for_report(url):
        parsed = urlsplit(url)
        sensitive_parameters = {
            "access_token",
            "apikey",
            "api_key",
            "authorization",
            "client_secret",
            "key",
            "password",
            "passwd",
            "refresh_token",
            "secret",
            "sig",
            "signature",
            "token",
        }
        query = []
        for key, value in parse_qsl(parsed.query, keep_blank_values=True):
            normalized_key = key.casefold().replace("-", "_")
            is_sensitive = normalized_key in sensitive_parameters or any(
                marker in normalized_key
                for marker in (
                    "token",
                    "secret",
                    "password",
                    "passwd",
                    "authorization",
                    "signature",
                    "credential",
                )
            ) or normalized_key.endswith("_key")
            query.append((key, "***" if is_sensitive else value))
        return urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), "")
        )

    @classmethod
    def fetch_records(cls, url, auth_config_id=""):
        url = cls.validate_url(url)
        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(b"Accept", b"application/json")
        if hasattr(request, "setTransferTimeout"):
            request.setTransferTimeout(REQUEST_TIMEOUT_MS)

        blocking = QgsBlockingNetworkRequest()
        if auth_config_id:
            blocking.setAuthCfg(auth_config_id)
        timeout_setter = getattr(blocking, "setTimeout", None)
        if timeout_setter:
            timeout_setter(REQUEST_TIMEOUT_MS)
        result = blocking.get(request, True)
        if result != QgsBlockingNetworkRequest.NoError:
            raise JsonSourceError(blocking.errorMessage() or "JSON request failed.")

        reply = blocking.reply()
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        if status and int(status) >= 400:
            raise JsonSourceError(f"Server returned HTTP {status}.")
        try:
            payload = json.loads(bytes(reply.content()).decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise JsonSourceError(f"Response was not valid JSON: {exc}") from exc
        return cls.records_from_payload(payload)

    @classmethod
    def records_from_payload(cls, payload):
        """Extract flat attribute records from common JSON and GeoJSON response shapes."""
        if isinstance(payload, list):
            records = payload
        elif isinstance(payload, Mapping):
            lowered_keys = {str(key).lower(): key for key in payload}
            if "features" in lowered_keys:
                records = payload[lowered_keys["features"]]
                if not isinstance(records, list):
                    raise JsonSourceError("The JSON 'features' member must be an array.")
            else:
                records = None
                for wrapper_key in ("records", "results", "items", "data"):
                    actual_key = lowered_keys.get(wrapper_key)
                    if actual_key is not None:
                        return cls.records_from_payload(payload[actual_key])
                if "properties" in lowered_keys and str(
                    payload.get(lowered_keys.get("type"), "")
                ).lower() == "feature":
                    records = [payload]
                else:
                    records = [payload]
        else:
            raise JsonSourceError(
                "JSON must contain an array of records, a record object, or a GeoJSON FeatureCollection."
            )

        normalized = []
        for index, record in enumerate(records):
            if not isinstance(record, Mapping):
                raise JsonSourceError(f"JSON record {index + 1} is not an object.")

            lowered_keys = {str(key).lower(): key for key in record}
            if (
                str(record.get(lowered_keys.get("type"), "")).lower() == "feature"
                and isinstance(record.get(lowered_keys.get("properties")), Mapping)
            ):
                record = record[lowered_keys["properties"]]
            normalized.append(cls._flatten_record(record))

        if not normalized or not any(normalized):
            raise JsonSourceError("The JSON response did not contain any records with attributes.")
        return normalized

    @classmethod
    def _flatten_record(cls, record, prefix=""):
        flattened = {}
        for key, value in record.items():
            field_name = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(value, Mapping):
                flattened.update(cls._flatten_record(value, field_name))
            elif isinstance(value, list):
                flattened[field_name] = json.dumps(value, ensure_ascii=False)
            else:
                flattened[field_name] = value
        return flattened
