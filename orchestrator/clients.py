"""HTTP clients for matrix Pi4 display APIs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import requests

from orchestrator.config import MatrixHostConfig


@dataclass
class HostResult:
    host_id: str
    label: str
    online: bool
    status_code: Optional[int] = None
    data: Optional[dict[str, Any]] = None
    error: Optional[str] = None


class MatrixHostClient:
    def __init__(self, cfg: MatrixHostConfig, timeout: float) -> None:
        self.cfg = cfg
        self.timeout = timeout

    def _request(self, method: str, path: str, **kwargs) -> HostResult:
        url = f"{self.cfg.api_base}{path}"
        try:
            resp = requests.request(method, url, timeout=self.timeout, **kwargs)
            data = None
            if resp.content:
                try:
                    data = resp.json()
                except ValueError:
                    data = {"raw": resp.text[:500]}
            if resp.ok:
                return HostResult(
                    host_id=self.cfg.id,
                    label=self.cfg.label,
                    online=True,
                    status_code=resp.status_code,
                    data=data,
                )
            detail = data.get("detail") if isinstance(data, dict) else resp.text[:200]
            return HostResult(
                host_id=self.cfg.id,
                label=self.cfg.label,
                online=False,
                status_code=resp.status_code,
                data=data,
                error=str(detail or resp.reason),
            )
        except requests.RequestException as exc:
            return HostResult(
                host_id=self.cfg.id,
                label=self.cfg.label,
                online=False,
                error=str(exc),
            )

    def get_state(self) -> HostResult:
        return self._request("GET", "/api/state")

    def get_modes(self) -> HostResult:
        return self._request("GET", "/api/modes")

    def get_media(self) -> HostResult:
        return self._request("GET", "/api/media")

    def set_mode(self, mode_id: str) -> HostResult:
        return self._request("PUT", f"/api/mode/{mode_id}")

    def set_media(self, path: str) -> HostResult:
        return self._request(
            "PUT",
            "/api/media",
            json={"path": path},
            headers={"Content-Type": "application/json"},
        )

    def get_mqtt(self) -> HostResult:
        return self._request("GET", "/api/mqtt")

    def set_mqtt(self, payload: dict[str, Any]) -> HostResult:
        return self._request(
            "PUT",
            "/api/mqtt",
            json=payload,
            headers={"Content-Type": "application/json"},
        )

    def get_flame_config(self) -> HostResult:
        return self.get_fire_config("flame")

    def set_flame_config(self, payload: dict[str, Any]) -> HostResult:
        return self.set_fire_config("flame", payload)

    def get_fire_config(self, mode_id: str) -> HostResult:
        return self._request("GET", f"/api/mode/{mode_id}/config")

    def set_fire_config(self, mode_id: str, payload: dict[str, Any]) -> HostResult:
        return self._request(
            "PUT",
            f"/api/mode/{mode_id}/config",
            json=payload,
            headers={"Content-Type": "application/json"},
        )

    def get_starfield_config(self) -> HostResult:
        return self._request("GET", "/api/mode/starfield/config")

    def set_starfield_config(self, payload: dict[str, Any]) -> HostResult:
        return self._request(
            "PUT",
            "/api/mode/starfield/config",
            json=payload,
            headers={"Content-Type": "application/json"},
        )

    def get_rain_config(self) -> HostResult:
        return self._request("GET", "/api/mode/matrix_rain/config")

    def set_rain_config(self, payload: dict[str, Any]) -> HostResult:
        return self._request(
            "PUT",
            "/api/mode/matrix_rain/config",
            json=payload,
            headers={"Content-Type": "application/json"},
        )

    def get_effect_config(self, mode_id: str) -> HostResult:
        return self._request("GET", f"/api/mode/{mode_id}/effect")

    def set_effect_config(self, mode_id: str, payload: dict[str, Any]) -> HostResult:
        return self._request(
            "PUT",
            f"/api/mode/{mode_id}/effect",
            json=payload,
            headers={"Content-Type": "application/json"},
        )

    def purge_mqtt(self) -> HostResult:
        return self._request("POST", "/api/mqtt/purge")

    def get_messages(self) -> HostResult:
        return self._request("GET", "/api/messages")

    def set_messages(self, messages: list[dict[str, Any]]) -> HostResult:
        return self._request("PUT", "/api/messages", json={"messages": messages})

    def preview_message(self, message: dict[str, Any], seconds: Optional[int] = None) -> HostResult:
        body: dict[str, Any] = {"message": message}
        if seconds:
            body["seconds"] = seconds
        return self._request("POST", "/api/messages/preview", json=body)
