"""Pi5 orchestrator FastAPI app — unified control for both matrix walls."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, List, Optional

import paho.mqtt.client as mqtt
from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from display.messages.schema import MessageError, for_target, normalize_message
from orchestrator.clients import HostResult, MatrixHostClient
from orchestrator.config import OrchestratorConfig, load_config
from orchestrator import messages as custom_messages
from orchestrator.messages_ui import MESSAGES_CSS, MESSAGES_HTML, MESSAGES_JS
from display.modes.effect_config import EFFECT_MODE_IDS
from web.effect_ui import EFFECT_CSS, EFFECT_JS
from orchestrator import mqtt_purge, offload_control, whisper_control
from orchestrator.self_test import get_runner as get_self_test_runner

_cfg: OrchestratorConfig = load_config()
_executor = ThreadPoolExecutor(max_workers=max(4, len(_cfg.matrix_hosts) * 2))

app = FastAPI(title="Spectra Orchestrator", version="0.1.0")


def _clients() -> List[MatrixHostClient]:
    return [
        MatrixHostClient(host, _cfg.request_timeout_seconds)
        for host in _cfg.matrix_hosts
    ]


def _client_for(host_id: str) -> MatrixHostClient:
    for host in _cfg.matrix_hosts:
        if host.id == host_id:
            return MatrixHostClient(host, _cfg.request_timeout_seconds)
    raise HTTPException(status_code=404, detail=f"Unknown host: {host_id}")


def _offload_host_for(host_id: str):
    for host in _cfg.offload_hosts:
        if host.id == host_id:
            return host
    raise HTTPException(status_code=404, detail=f"Unknown offload host: {host_id}")


def _map_hosts(fn) -> List[HostResult]:
    clients = _clients()
    results: List[HostResult] = []
    futures = {_executor.submit(fn, c): c for c in clients}
    for future in as_completed(futures):
        results.append(future.result())
    order = {h.id: i for i, h in enumerate(_cfg.matrix_hosts)}
    results.sort(key=lambda r: order.get(r.host_id, 99))
    return results


def _host_payload(result: HostResult) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": result.host_id,
        "label": result.label,
        "online": result.online,
        "status_code": result.status_code,
        "error": result.error,
    }
    if result.data is not None:
        payload["state"] = result.data
    return payload


class MediaSelectRequest(BaseModel):
    path: str = Field(..., min_length=1)


class MqttTestRequest(BaseModel):
    text: str = Field(default="Spectra orchestrator test", min_length=1, max_length=500)
    ttl: int = Field(default=15, ge=1, le=300)
    color: List[int] = Field(default=[0, 255, 120])
    topic: Optional[str] = None


class WhisperEnableRequest(BaseModel):
    enabled: bool


class MqttOverlayUpdateRequest(BaseModel):
    overlay_enabled: Optional[bool] = None
    sources: Optional[dict[str, bool]] = None


class SelfTestRunRequest(BaseModel):
    dwell_seconds: float = Field(default=6.0, ge=3.0, le=15.0)


class FlameConfigRequest(BaseModel):
    preset: Optional[str] = None
    intensity: Optional[int] = None
    core: Optional[List[int]] = None
    mid: Optional[List[int]] = None
    tip: Optional[List[int]] = None
    ember: Optional[List[int]] = None
    color_rotate_speed: Optional[int] = None


class StarfieldConfigRequest(BaseModel):
    preset: Optional[str] = None
    color_mode: Optional[str] = None
    intensity: Optional[int] = None
    near: Optional[List[int]] = None
    mid: Optional[List[int]] = None
    far: Optional[List[int]] = None
    color_rotate_speed: Optional[int] = None


class MatrixRainConfigRequest(BaseModel):
    preset: Optional[str] = None
    color: Optional[List[int]] = None
    speed: Optional[int] = None


@app.get("/api/health")
def api_health() -> dict[str, Any]:
    probes = _map_hosts(lambda c: c.get_state())
    online = sum(1 for p in probes if p.online)
    whisper = whisper_control.get_status().as_dict()
    return {
        "orchestrator": "ok",
        "hosts_online": online,
        "hosts_total": len(probes),
        "hosts": [_host_payload(p) for p in probes],
        "whisper": whisper,
    }


@app.get("/api/whisper/status")
def api_whisper_status() -> dict[str, Any]:
    return whisper_control.get_status().as_dict()


@app.put("/api/whisper/enabled")
def api_whisper_enabled(body: WhisperEnableRequest) -> dict[str, Any]:
    try:
        status = whisper_control.set_enabled(body.enabled)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return status.as_dict()


@app.get("/api/self-test/status")
def api_self_test_status() -> dict[str, Any]:
    return get_self_test_runner(_cfg).status()


@app.post("/api/self-test/run")
def api_self_test_run(body: SelfTestRunRequest) -> dict[str, Any]:
    try:
        return get_self_test_runner(_cfg).start(body.dwell_seconds)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/hosts")
def api_hosts() -> List[dict[str, Any]]:
    return [_host_payload(r) for r in _map_hosts(lambda c: c.get_state())]


@app.get("/api/hosts/{host_id}/state")
def api_host_state(host_id: str) -> dict[str, Any]:
    result = _client_for(host_id).get_state()
    if not result.online:
        raise HTTPException(status_code=502, detail=result.error or "host unreachable")
    return _host_payload(result)


@app.get("/api/modes")
def api_modes() -> List[dict[str, Any]]:
    for client in _clients():
        result = client.get_modes()
        if result.online and isinstance(result.data, list):
            return result.data
    raise HTTPException(status_code=502, detail="No matrix host returned mode list")


@app.get("/api/hosts/{host_id}/media")
def api_host_media(host_id: str) -> List[dict[str, Any]]:
    result = _client_for(host_id).get_media()
    if not result.online:
        raise HTTPException(status_code=502, detail=result.error or "host unreachable")
    return result.data if isinstance(result.data, list) else []


@app.put("/api/sync/mode/{mode_id}")
def api_sync_mode(mode_id: str) -> dict[str, Any]:
    results = _map_hosts(lambda c: c.set_mode(mode_id))
    return {
        "mode_id": mode_id,
        "results": [_host_payload(r) for r in results],
        "all_ok": all(r.online for r in results),
    }


@app.put("/api/hosts/{host_id}/mode/{mode_id}")
def api_host_mode(host_id: str, mode_id: str) -> dict[str, Any]:
    result = _client_for(host_id).set_mode(mode_id)
    if not result.online:
        raise HTTPException(status_code=502, detail=result.error or "host unreachable")
    return _host_payload(result)


@app.put("/api/sync/mode/{mode_id}/config")
def api_sync_fire_config(mode_id: str, body: FlameConfigRequest) -> dict[str, Any]:
    if mode_id not in ("flame", "lava"):
        raise HTTPException(status_code=404, detail="Unknown fire mode")
    payload = body.model_dump(exclude_none=True)
    if not payload:
        raise HTTPException(status_code=400, detail="Provide preset or color")
    results = _map_hosts(lambda c: c.set_fire_config(mode_id, payload))
    return {
        "mode": mode_id,
        "config": payload,
        "results": [_host_payload(r) for r in results],
        "all_ok": all(r.online for r in results),
    }


@app.get("/api/hosts/{host_id}/mode/starfield/config")
def api_host_starfield_config_get(host_id: str) -> dict[str, Any]:
    result = _client_for(host_id).get_starfield_config()
    if not result.online:
        raise HTTPException(status_code=502, detail=result.error or "host unreachable")
    return result.data if isinstance(result.data, dict) else {}


@app.put("/api/hosts/{host_id}/mode/starfield/config")
def api_host_starfield_config(host_id: str, body: StarfieldConfigRequest) -> dict[str, Any]:
    payload = body.model_dump(exclude_none=True)
    if not payload:
        raise HTTPException(status_code=400, detail="Provide preset, color_mode, intensity, and/or stops")
    result = _client_for(host_id).set_starfield_config(payload)
    if not result.online:
        raise HTTPException(status_code=502, detail=result.error or "host unreachable")
    return result.data if isinstance(result.data, dict) else {}


@app.get("/api/hosts/{host_id}/mode/matrix_rain/config")
def api_host_rain_config_get(host_id: str) -> dict[str, Any]:
    result = _client_for(host_id).get_rain_config()
    if not result.online:
        raise HTTPException(status_code=502, detail=result.error or "host unreachable")
    return result.data if isinstance(result.data, dict) else {}


@app.put("/api/hosts/{host_id}/mode/matrix_rain/config")
def api_host_rain_config(host_id: str, body: MatrixRainConfigRequest) -> dict[str, Any]:
    payload = body.model_dump(exclude_none=True)
    if not payload:
        raise HTTPException(status_code=400, detail="Provide preset, color, and/or speed")
    result = _client_for(host_id).set_rain_config(payload)
    if not result.online:
        raise HTTPException(status_code=502, detail=result.error or "host unreachable")
    return result.data if isinstance(result.data, dict) else {}


def _effect_result(result) -> dict[str, Any]:
    if not result.online:
        # Pass the wall's own 4xx (bad setting, unknown effect) through unchanged.
        status = result.status_code if result.status_code and result.status_code < 500 else 502
        raise HTTPException(status_code=status, detail=result.error or "host unreachable")
    return result.data if isinstance(result.data, dict) else {}


@app.get("/api/hosts/{host_id}/mode/{mode_id}/effect")
def api_host_effect_get(host_id: str, mode_id: str) -> dict[str, Any]:
    return _effect_result(_client_for(host_id).get_effect_config(mode_id))


@app.put("/api/hosts/{host_id}/mode/{mode_id}/effect")
def api_host_effect_set(host_id: str, mode_id: str, body: dict = Body(...)) -> dict[str, Any]:
    return _effect_result(_client_for(host_id).set_effect_config(mode_id, body))


@app.put("/api/hosts/{host_id}/mode/{mode_id}/config")
def api_host_fire_config(host_id: str, mode_id: str, body: FlameConfigRequest) -> dict[str, Any]:
    if mode_id not in ("flame", "lava"):
        raise HTTPException(status_code=404, detail="Unknown fire mode")
    payload = body.model_dump(exclude_none=True)
    if not payload:
        raise HTTPException(status_code=400, detail="Provide preset and/or color stops")
    result = _client_for(host_id).set_fire_config(mode_id, payload)
    if not result.online:
        raise HTTPException(status_code=502, detail=result.error or "host unreachable")
    return result.data if isinstance(result.data, dict) else {}


@app.get("/api/hosts/{host_id}/mode/{mode_id}/config")
def api_host_fire_config_get(host_id: str, mode_id: str) -> dict[str, Any]:
    if mode_id not in ("flame", "lava"):
        raise HTTPException(status_code=404, detail="Unknown fire mode")
    result = _client_for(host_id).get_fire_config(mode_id)
    if not result.online:
        raise HTTPException(status_code=502, detail=result.error or "host unreachable")
    return result.data if isinstance(result.data, dict) else {}


@app.put("/api/sync/media")
def api_sync_media(body: MediaSelectRequest) -> dict[str, Any]:
    results = _map_hosts(lambda c: c.set_media(body.path))
    return {
        "path": body.path,
        "results": [_host_payload(r) for r in results],
        "all_ok": all(r.online for r in results),
    }


@app.put("/api/hosts/{host_id}/media")
def api_host_media_select(host_id: str, body: MediaSelectRequest) -> dict[str, Any]:
    result = _client_for(host_id).set_media(body.path)
    if not result.online:
        raise HTTPException(status_code=502, detail=result.error or "host unreachable")
    return _host_payload(result)


@app.get("/api/hosts/{host_id}/mqtt")
def api_host_mqtt(host_id: str) -> dict[str, Any]:
    result = _client_for(host_id).get_mqtt()
    if not result.online:
        raise HTTPException(status_code=502, detail=result.error or "host unreachable")
    return result.data if isinstance(result.data, dict) else {}


@app.put("/api/hosts/{host_id}/mqtt")
def api_host_mqtt_update(host_id: str, body: MqttOverlayUpdateRequest) -> dict[str, Any]:
    payload = body.model_dump(exclude_none=True)
    result = _client_for(host_id).set_mqtt(payload)
    if not result.online:
        raise HTTPException(status_code=502, detail=result.error or "host unreachable")
    return result.data if isinstance(result.data, dict) else {}


@app.get("/api/offload")
def api_offload() -> List[dict[str, Any]]:
    return [s.as_dict() for s in offload_control.get_status(_cfg.offload_hosts)]


@app.post("/api/offload/{host_id}/purge-queue")
def api_offload_purge_queue(host_id: str) -> dict[str, Any]:
    cfg = _offload_host_for(host_id)
    try:
        return offload_control.purge_queue(cfg).as_dict()
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def _purge_whisper_queue() -> dict[str, Any]:
    """Raises RuntimeError if a host can't be reached."""
    if _cfg.offload_hosts:
        return offload_control.purge_queue(_cfg.offload_hosts[0]).as_dict()
    pending = whisper_control.count_pending_queue()
    deleted = whisper_control.purge_pending_queue()
    return {
        "host_id": None,
        "pi5_deleted": deleted,
        "remote_deleted": 0,
        "pi5_pending_before": pending,
        "remote_pending_before": 0,
    }


@app.post("/api/whisper/purge-queue")
def api_whisper_purge_queue() -> dict[str, Any]:
    """Drop pending chunks on Pi5 and the first offload host (if configured)."""
    try:
        return _purge_whisper_queue()
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/mqtt/purge")
def api_mqtt_purge() -> dict[str, Any]:
    """Stop stale captions everywhere: Whisper backlog, retained topics, walls.

    Order matters: drain the sources first so nothing old is published after
    the walls are cleared. Each stage reports separately; one failing doesn't
    stop the rest.
    """
    result: dict[str, Any] = {}
    try:
        result["whisper"] = _purge_whisper_queue()
    except Exception as exc:
        result["whisper"] = {"error": str(exc)}
    try:
        result["retained_cleared"] = mqtt_purge.clear_retained(_cfg.mqtt.broker, _cfg.mqtt.port)
    except Exception as exc:
        result["retained_cleared"] = None
        result["retained_error"] = f"MQTT broker: {exc}"
    result["walls"] = [_host_payload(r) for r in _map_hosts(lambda c: c.purge_mqtt())]
    result["ok"] = (
        "error" not in result["whisper"]
        and result["retained_cleared"] is not None
        and all(w["online"] for w in result["walls"])
    )
    return result


@app.post("/api/mqtt/test")
def api_mqtt_test(body: MqttTestRequest) -> dict[str, Any]:
    topic = body.topic or _cfg.mqtt.test_topic
    if len(body.color) != 3:
        raise HTTPException(status_code=400, detail="color must be [r, g, b]")
    payload = json.dumps({"text": body.text, "ttl": body.ttl, "color": body.color})
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    try:
        client.connect(_cfg.mqtt.broker, _cfg.mqtt.port, 60)
        client.loop_start()
        info = client.publish(topic, payload, qos=0)
        info.wait_for_publish(timeout=3.0)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"MQTT publish failed: {exc}") from exc
    finally:
        try:
            client.loop_stop()
            client.disconnect()
        except Exception:
            pass
    return {"published": True, "topic": topic, "payload": json.loads(payload)}


def _publish_messages_config(state: dict[str, Any]) -> Optional[str]:
    try:
        custom_messages.publish(
            _cfg.mqtt.broker, _cfg.mqtt.port, _cfg.messages.topic,
            custom_messages.config_payload(state, _cfg.messages.timezone), retain=True,
        )
    except Exception as exc:
        return f"MQTT publish failed: {exc}"
    return None


def _push_messages(messages: List[dict[str, Any]], only_out_of_sync: bool = False) -> List[HostResult]:
    def push(client: MatrixHostClient) -> HostResult:
        mine = for_target(messages, client.cfg.id)
        if only_out_of_sync:
            current = client.get_messages()
            if not current.online:
                return current
            if (current.data or {}).get("revision") == custom_messages.wall_revision(messages, client.cfg.id):
                return current
        return client.set_messages(mine)

    return _map_hosts(push)


def _messages_status(push_results: Optional[List[HostResult]] = None) -> dict[str, Any]:
    master = custom_messages.load_master()
    results = push_results or _map_hosts(lambda c: c.get_messages())
    hosts = []
    for result in results:
        data = result.data if isinstance(result.data, dict) else {}
        expected = custom_messages.wall_revision(master["messages"], result.host_id)
        hosts.append({
            "id": result.host_id,
            "label": result.label,
            "online": result.online,
            "error": result.error,
            "in_sync": result.online and data.get("revision") == expected,
            "count": len(data.get("messages") or []),
            "now_showing": data.get("now_showing"),
            "next_showing": data.get("next_showing"),
            "preview": data.get("preview"),
        })
    return {
        **master,
        "hosts": hosts,
        "host_ids": [h.id for h in _cfg.matrix_hosts],
        "mqtt_topic": _cfg.messages.topic,
        "timezone": _cfg.messages.timezone,
    }


def _resync_walls() -> None:
    master = custom_messages.load_master()
    if master["updated_at"] is not None:
        _push_messages(master["messages"], only_out_of_sync=True)


_messages_resync = custom_messages.WallResync(_resync_walls)


@app.on_event("startup")
def _start_messages_resync() -> None:
    _messages_resync.start()


@app.get("/api/messages")
def api_messages() -> dict[str, Any]:
    return _messages_status()


@app.put("/api/messages")
def api_messages_save(body: dict = Body(...)) -> dict[str, Any]:
    try:
        state = custom_messages.save_master(body.get("messages"))
    except MessageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    results = _push_messages(state["messages"])
    status = _messages_status(results)
    status["mqtt_error"] = _publish_messages_config(state)
    return status


@app.post("/api/messages/sync")
def api_messages_sync() -> dict[str, Any]:
    state = custom_messages.load_master()
    results = _push_messages(state["messages"])
    status = _messages_status(results)
    status["mqtt_error"] = _publish_messages_config(state)
    return status


@app.post("/api/messages/preview")
def api_messages_preview(body: dict = Body(...)) -> dict[str, Any]:
    """Show a (possibly unsaved) message now on every display it targets."""
    try:
        message = normalize_message(body.get("message"))
    except MessageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    seconds = body.get("seconds")
    targets = message["targets"]
    clients = [c for c in _clients() if "all" in targets or c.cfg.id in targets]
    futures = [_executor.submit(c.preview_message, message, seconds) for c in clients]
    walls = [_host_payload(f.result()) for f in futures]
    mqtt_error = None
    try:
        custom_messages.publish(
            _cfg.mqtt.broker, _cfg.mqtt.port, _cfg.messages.preview_topic,
            {"message": message, "seconds": seconds or message["duration_seconds"]}, retain=False,
        )
    except Exception as exc:
        mqtt_error = f"MQTT publish failed: {exc}"
    return {"walls": walls, "mqtt_error": mqtt_error}


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    host_ids = json.dumps([h.id for h in _cfg.matrix_hosts])
    host_sections = []
    for host in _cfg.matrix_hosts:
        host_sections.append(
            f"""
    <section class="host-card" id="host-{host.id}">
      <h2><span>{host.label}</span><span class="badge" data-host="{host.id}">…</span></h2>
      <p class="status-line">Mode: <strong data-field="mode">—</strong>
        <span data-field="media"></span></p>
      <div class="mode-grid host-modes" data-host="{host.id}"></div>
      <div class="wall-flame-panel" data-fire-panel="{host.id}" style="display:none;margin-top:0.75rem">
        <p class="hint" data-fire-title="{host.id}" style="margin:0 0 0.35rem">Fire colors ({host.label})</p>
        <div class="flame-swatches" data-fire-swatches="{host.id}"></div>
        <div class="flame-intensity" data-fire-intensity="{host.id}"></div>
        <div class="flame-intensity" data-fire-rotate="{host.id}" style="margin-top:0.35rem"></div>
        <div class="flame-stops" data-fire-stops="{host.id}"></div>
      </div>
      <div class="wall-flame-panel" data-star-panel="{host.id}" style="display:none;margin-top:0.75rem">
        <p class="hint" style="margin:0 0 0.35rem">Starfield ({host.label})</p>
        <div class="flame-intensity" data-star-intensity="{host.id}"></div>
        <div class="flame-intensity" data-star-modes="{host.id}" style="margin-top:0.35rem"></div>
        <div class="flame-intensity" data-star-rotate="{host.id}" style="margin-top:0.35rem"></div>
        <div class="flame-swatches" data-star-swatches="{host.id}"></div>
        <div class="flame-stops" data-star-stops="{host.id}"></div>
      </div>
      <div class="wall-flame-panel" data-rain-panel="{host.id}" style="display:none;margin-top:0.75rem">
        <p class="hint" style="margin:0 0 0.35rem">Matrix rain ({host.label})</p>
        <div class="flame-intensity" data-rain-speed="{host.id}"></div>
        <div class="flame-swatches" data-rain-swatches="{host.id}"></div>
        <div class="flame-stops">
          <label class="flame-stop"><span>Custom color</span>
            <input type="color" data-rain-color="{host.id}" value="#00ff46"></label>
        </div>
      </div>
      <div class="wall-flame-panel" data-effect-panel="{host.id}" style="display:none;margin-top:0.75rem">
        <p class="hint" style="margin:0 0 0.35rem"><span data-effect-title="{host.id}"></span> ({host.label})</p>
        <div data-effect-controls="{host.id}"></div>
      </div>
      <h2 style="margin-top:1rem">MQTT overlay</h2>
      <div class="mqtt-box">
        <div class="mqtt-row">
          <span class="mqtt-title">Show MQTT on this wall</span>
          <label class="switch" title="MQTT overlay for {host.label}">
            <input type="checkbox" class="wall-mqtt-master" data-host="{host.id}">
            <span class="slider"></span>
          </label>
        </div>
        <div class="wall-mqtt-sources" data-sources="{host.id}"><em>Loading…</em></div>
      </div>
      <h2 style="margin-top:1rem">Media</h2>
      <div class="media-list" data-media="{host.id}"><em>Loading…</em></div>
    </section>"""
        )
    host_sections_html = "".join(host_sections)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Spectra Orchestrator</title>
  <style>
    :root {{
      color-scheme: dark;
      font-family: system-ui, sans-serif;
      background: #0b0d11;
      color: #e8eaed;
    }}
    body {{ margin: 0; padding: 1.25rem 1.5rem 3rem; }}
    header {{ display: flex; flex-wrap: wrap; gap: 1rem; align-items: baseline; margin-bottom: 1.5rem; }}
    h1 {{ font-size: 1.35rem; margin: 0; }}
    .summary {{ color: #9aa0a6; font-size: 0.95rem; }}
    .summary strong {{ color: #e8eaed; }}
    .layout {{ display: grid; gap: 1.25rem; grid-template-columns: repeat(auto-fit, minmax(18rem, 1fr)); }}
    section {{
      background: #12151c; border: 1px solid #2a2f3a; border-radius: 12px;
      padding: 1rem 1.1rem 1.2rem;
    }}
    section h2 {{ margin: 0 0 0.75rem; font-size: 0.95rem; color: #9aa0a6; font-weight: 600; }}
    .host-card h2 {{ display: flex; justify-content: space-between; align-items: center; }}
    .badge {{
      font-size: 0.75rem; padding: 0.15rem 0.5rem; border-radius: 999px;
      border: 1px solid #3d4450; color: #9aa0a6;
    }}
    .badge.online {{ border-color: #3d9970; color: #7dcea0; }}
    .badge.offline {{ border-color: #a04040; color: #e57373; }}
    .mode-grid, .media-list {{ display: grid; gap: 0.5rem; }}
    button {{
      text-align: left; cursor: pointer; color: inherit;
      background: #1a1d24; border: 1px solid #30343c; border-radius: 8px;
      padding: 0.65rem 0.75rem;
    }}
    button:hover {{ border-color: #5f9cff; }}
    button.active {{ border-color: #5f9cff; background: #152033; }}
    button.sync {{ font-weight: 600; }}
    .status-line {{ color: #9aa0a6; font-size: 0.9rem; margin-bottom: 0.75rem; }}
    .status-line strong {{ color: #cbd5e1; }}
    .hint {{ color: #6b7280; font-size: 0.82rem; margin: 0 0 0.65rem; }}
    .media-list {{ max-height: 14rem; overflow-y: auto; }}
    .media-btn span {{ color: #6b7280; font-size: 0.78rem; margin-left: 0.35rem; }}
    .toolbar {{ display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: 0.75rem; }}
    .toolbar button {{ flex: 1 1 auto; min-width: 8rem; text-align: center; }}
    #toast {{
      position: fixed; bottom: 1rem; right: 1rem; display: none;
      background: #1e3a2f; border: 1px solid #3d9970;
      padding: 0.75rem 1rem; border-radius: 8px; max-width: 22rem;
    }}
    .wide {{ grid-column: 1 / -1; }}
    .toggle-row {{
      display: flex; align-items: center; gap: 0.75rem; cursor: pointer;
      user-select: none; margin: 0.25rem 0 0.5rem;
    }}
    .toggle-row input {{ position: absolute; opacity: 0; width: 0; height: 0; }}
    .toggle-slider {{
      width: 2.75rem; height: 1.5rem; background: #30343c; border-radius: 999px;
      position: relative; transition: background 0.2s; flex-shrink: 0;
    }}
    .toggle-slider::after {{
      content: ""; position: absolute; top: 0.2rem; left: 0.2rem;
      width: 1.1rem; height: 1.1rem; background: #e8eaed; border-radius: 50%;
      transition: transform 0.2s;
    }}
    .toggle-row input:checked + .toggle-slider {{ background: #3d9970; }}
    .toggle-row input:checked + .toggle-slider::after {{ transform: translateX(1.25rem); }}
    .toggle-row input:disabled + .toggle-slider {{ opacity: 0.5; }}
    #whisper-label {{ font-weight: 600; color: #cbd5e1; }}
    #whisper-detail {{ margin-top: 0; }}
    .selftest-panel {{
      display: flex; flex-wrap: wrap; gap: 0.75rem; align-items: center; margin-top: 0.5rem;
    }}
    .selftest-panel label {{ color: #9aa0a6; font-size: 0.9rem; }}
    .selftest-panel input[type=range] {{ width: 8rem; }}
    #selftest-run {{
      background: linear-gradient(135deg, #1a3a5c, #2a5298);
      border-color: #5f9cff; font-weight: 700; min-width: 12rem;
    }}
    #selftest-run:disabled {{ opacity: 0.5; cursor: not-allowed; }}
    #selftest-modal {{
      display: none; position: fixed; inset: 0; z-index: 1000;
      background: rgba(5, 8, 14, 0.92); backdrop-filter: blur(4px);
      align-items: center; justify-content: center; padding: 1.5rem;
    }}
    #selftest-modal.open {{ display: flex; }}
    .selftest-card {{
      width: min(42rem, 100%); background: #12151c; border: 1px solid #3d5a80;
      border-radius: 16px; padding: 1.5rem 1.75rem 1.75rem;
      box-shadow: 0 24px 48px rgba(0,0,0,0.45);
    }}
    .selftest-card h2 {{ margin: 0 0 0.35rem; font-size: 1.35rem; color: #e8eaed; }}
    .selftest-sub {{ color: #9aa0a6; margin: 0 0 1rem; font-size: 0.95rem; }}
    .progress-track {{
      height: 0.55rem; background: #1a1d24; border-radius: 999px; overflow: hidden;
      margin: 0.75rem 0 1rem;
    }}
    .progress-fill {{
      height: 100%; width: 0%; background: linear-gradient(90deg, #3d9970, #5f9cff);
      transition: width 0.35s ease;
    }}
    #selftest-current {{
      font-size: 1.05rem; font-weight: 600; color: #cbd5e1; min-height: 1.5rem;
    }}
    #selftest-summary {{ color: #9aa0a6; font-size: 0.9rem; margin-bottom: 0.75rem; }}
    .step-list {{
      max-height: 16rem; overflow-y: auto; display: grid; gap: 0.35rem;
      font-size: 0.85rem;
    }}
    .step-row {{
      display: grid; grid-template-columns: 5.5rem 1fr; gap: 0.5rem;
      padding: 0.35rem 0.5rem; border-radius: 6px; background: #0b0d11;
    }}
    .step-row.running {{ outline: 1px solid #5f9cff; }}
    .step-status {{ font-weight: 700; text-transform: uppercase; font-size: 0.75rem; }}
    .step-status.pass {{ color: #7dcea0; }}
    .step-status.fail {{ color: #e57373; }}
    .step-status.warn {{ color: #f0c674; }}
    .step-status.running {{ color: #5f9cff; }}
    .step-status.pending {{ color: #6b7280; }}
    .selftest-actions {{ margin-top: 1rem; text-align: right; }}
    .switch {{ position: relative; width: 2.6rem; height: 1.45rem; flex-shrink: 0; }}
    .switch input {{ opacity: 0; width: 0; height: 0; }}
    .switch .slider {{
      position: absolute; inset: 0; cursor: pointer; background: #3a3f4b;
      border-radius: 999px; transition: 0.2s;
    }}
    .switch .slider::before {{
      content: ""; position: absolute; height: 1.05rem; width: 1.05rem;
      left: 0.2rem; bottom: 0.2rem; background: #e8eaed; border-radius: 50%;
      transition: 0.2s;
    }}
    .switch input:checked + .slider {{ background: #3d7eff; }}
    .switch input:checked + .slider::before {{ transform: translateX(1.15rem); }}
    .mqtt-box {{ display: grid; gap: 0.45rem; }}
    .mqtt-row {{ display: flex; align-items: center; justify-content: space-between; gap: 0.75rem; }}
    .mqtt-title {{ color: #cbd5e1; font-size: 0.9rem; }}
    .wall-mqtt-sources {{ display: grid; gap: 0.3rem; padding-left: 0.15rem; }}
    .src-check {{ display: flex; align-items: center; gap: 0.5rem; font-size: 0.85rem; color: #cbd5e1; cursor: pointer; }}
    .src-check input {{ width: 0.95rem; height: 0.95rem; accent-color: #5f9cff; }}
    .src-check.disabled {{ opacity: 0.45; cursor: default; }}
    .offload-grid {{ display: grid; gap: 0.75rem; grid-template-columns: repeat(auto-fit, minmax(20rem, 1fr)); }}
    .offload-card {{ background: #0b0d11; border: 1px solid #2a2f3a; border-radius: 10px; padding: 0.8rem 0.9rem; }}
    .offload-card h3 {{ margin: 0 0 0.55rem; font-size: 0.95rem; display: flex; justify-content: space-between; align-items: center; gap: 0.5rem; }}
    .offload-actions {{ margin-top: 0.65rem; }}
    .offload-actions button {{ width: 100%; text-align: center; font-size: 0.88rem; padding: 0.5rem 0.65rem; }}
    .chips {{ display: flex; flex-wrap: wrap; gap: 0.4rem; }}
    .chip {{ font-size: 0.75rem; padding: 0.15rem 0.55rem; border-radius: 999px; border: 1px solid #3d4450; color: #9aa0a6; }}
    .chip.ok {{ border-color: #3d9970; color: #7dcea0; }}
    .chip.bad {{ border-color: #a04040; color: #e57373; }}
    .chip.warn {{ border-color: #b8860b; color: #f0c674; }}
    .flame-swatches {{ display: flex; flex-wrap: wrap; gap: 0.45rem; margin-top: 0.5rem; }}
    .flame-swatch {{
      width: 2rem; height: 2rem; border-radius: 8px; border: 2px solid #30343c;
      cursor: pointer; padding: 0;
    }}
    .flame-swatch.active {{ border-color: #5f9cff; box-shadow: 0 0 0 1px #5f9cff; }}
    .flame-stops {{ display: grid; gap: 0.35rem; margin-top: 0.5rem; }}
    .flame-stop {{ display: flex; align-items: center; justify-content: space-between; gap: 0.5rem; font-size: 0.82rem; color: #cbd5e1; }}
    .flame-stop input[type=color] {{ width: 2rem; height: 1.5rem; border: 1px solid #30343c; border-radius: 6px; background: #0f1115; cursor: pointer; padding: 0; }}
    .flame-intensity {{ display: flex; flex-wrap: wrap; gap: 0.35rem; margin-top: 0.45rem; }}
    .flame-intensity button {{
      flex: 1 1 auto; min-width: 4rem; text-align: center; padding: 0.4rem 0.45rem;
      background: #1a1d24; border: 1px solid #30343c; border-radius: 8px; color: inherit; cursor: pointer; font-size: 0.78rem;
    }}
    .flame-intensity button.active {{ border-color: #5f9cff; background: #152033; }}
{MESSAGES_CSS}
{EFFECT_CSS}
  </style>
</head>
<body>
  <header>
    <h1>Spectra Orchestrator</h1>
    <p class="summary" id="health-summary">Loading status…</p>
  </header>

  <div class="layout">
    <section class="wide">
      <h2>Full system self-test</h2>
      <p class="hint">Cycles both matrix walls through display modes with MQTT banners, then validates Pi5 hardware. ~2–3 min at default dwell.</p>
      <div class="selftest-panel">
        <button type="button" id="selftest-run">▶ Run full self-test</button>
        <label>Dwell per mode: <input type="range" id="selftest-dwell" min="3" max="12" value="6"> <span id="selftest-dwell-val">6s</span></label>
      </div>
    </section>

    <section class="wide">
      <h2>Whisper pipeline</h2>
      <p class="hint">ReSpeaker → faster-whisper (auto-detect → English) → MQTT overlay.</p>
      <label class="toggle-row" for="whisper-toggle">
        <input type="checkbox" id="whisper-toggle">
        <span class="toggle-slider"></span>
        <span id="whisper-label">Whisper …</span>
      </label>
      <p class="status-line" id="whisper-detail">Checking services…</p>
      <div class="toolbar" style="margin-top:0.5rem">
        <button type="button" id="whisper-purge" title="Delete pending audio chunks on Pi5 and offload host">Purge queue</button>
      </div>
    </section>

    <section class="wide" id="offload-section" style="display:none">
      <h2>Whisper inference offload</h2>
      <p class="hint">Pi5 forwards audio chunks to an offload host that runs transcription and publishes captions back to MQTT.</p>
      <div class="offload-grid" id="offload-grid"></div>
    </section>

    <section class="wide">
      <h2>Sync both walls</h2>
      <p class="hint">Set the same display mode on upper and lower.</p>
      <div class="mode-grid" id="sync-modes"><em>Loading modes…</em></div>
      <div class="toolbar">
        <button type="button" id="mqtt-test">MQTT overlay test</button>
        <button type="button" id="mqtt-purge" title="Clear stale captions: Whisper backlog, retained broker topics, and what the walls are showing">Purge MQTT everywhere</button>
        <button type="button" id="refresh">Refresh now</button>
      </div>
    </section>
{MESSAGES_HTML}
{host_sections_html}
  </div>

  <div id="toast"></div>
  <div id="selftest-modal" aria-hidden="true">
    <div class="selftest-card">
      <h2>Spectra self-test</h2>
      <p class="selftest-sub" id="selftest-modal-sub">Running diagnostics…</p>
      <div class="progress-track"><div class="progress-fill" id="selftest-progress"></div></div>
      <p id="selftest-summary">—</p>
      <p id="selftest-current">Starting…</p>
      <div class="step-list" id="selftest-steps"></div>
      <div class="selftest-actions">
        <button type="button" id="selftest-close" disabled>Close</button>
      </div>
    </div>
  </div>
  <script>
    const HOST_IDS = {host_ids};
    const EFFECT_MODES = {json.dumps(list(EFFECT_MODE_IDS))};
    const toast = document.getElementById("toast");
    const whisperToggle = document.getElementById("whisper-toggle");
    const whisperPurgeBtn = document.getElementById("whisper-purge");
    let whisperBusy = false;
    let purgeBusy = false;
    let selfTestPoll = null;

    const selfTestModal = document.getElementById("selftest-modal");
    const selfTestRunBtn = document.getElementById("selftest-run");
    const selfTestDwell = document.getElementById("selftest-dwell");
    const selfTestDwellVal = document.getElementById("selftest-dwell-val");
    selfTestDwell.addEventListener("input", () => {{
      selfTestDwellVal.textContent = selfTestDwell.value + "s";
    }});

    function renderSelfTest(data) {{
      const prog = data.progress || {{}};
      const sum = data.summary || {{}};
      const pct = prog.total ? Math.round((prog.done / prog.total) * 100) : 0;
      document.getElementById("selftest-progress").style.width = pct + "%";
      document.getElementById("selftest-summary").textContent =
        data.running
          ? `${{prog.done || 0}} / ${{prog.total || "?"}} steps · ${{sum.duration_sec || 0}}s elapsed`
          : `Done — ${{sum.passed || 0}} passed, ${{sum.failed || 0}} failed, ${{sum.warned || 0}} warnings · ${{sum.duration_sec || 0}}s`;
      const cur = data.current_step;
      document.getElementById("selftest-current").textContent =
        cur ? cur.name : (data.running ? "…" : (sum.ok ? "All checks passed" : "Completed with failures"));
      document.getElementById("selftest-modal-sub").textContent =
        data.running ? "Matrix demos + hardware validation in progress" : "Self-test finished";
      document.getElementById("selftest-steps").innerHTML = (data.steps || []).map(s => `
        <div class="step-row ${{s.status}}">
          <span class="step-status ${{s.status}}">${{s.status}}</span>
          <span><strong>${{s.name}}</strong><br><span style="color:#6b7280">${{s.message || ""}}</span></span>
        </div>`).join("");
      selfTestRunBtn.disabled = !!data.running;
      document.getElementById("selftest-close").disabled = !!data.running;
    }}

    async function pollSelfTest() {{
      try {{
        const res = await fetch("/api/self-test/status");
        const data = await res.json();
        renderSelfTest(data);
        if (!data.running) {{
          clearInterval(selfTestPoll);
          selfTestPoll = null;
          refresh();
          showToast(data.summary?.ok ? "Self-test passed" : "Self-test finished — see results");
        }}
      }} catch (e) {{
        console.error(e);
      }}
    }}

    document.getElementById("selftest-close").addEventListener("click", () => {{
      selfTestModal.classList.remove("open");
    }});

    selfTestRunBtn.addEventListener("click", async () => {{
      if (selfTestPoll) return;
      selfTestModal.classList.add("open");
      renderSelfTest({{ running: true, progress: {{ done: 0, total: 0 }}, steps: [], summary: {{}} }});
      try {{
        const res = await fetch("/api/self-test/run", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{ dwell_seconds: Number(selfTestDwell.value) }}),
        }});
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to start");
        renderSelfTest(data);
        selfTestPoll = setInterval(pollSelfTest, 600);
        pollSelfTest();
      }} catch (err) {{
        showToast(err.message || "Self-test failed to start");
        selfTestModal.classList.remove("open");
      }}
    }});

    function renderWhisper(whisper) {{
      if (!whisper || whisperBusy) return;
      whisperToggle.checked = !!whisper.enabled;
      whisperToggle.disabled = false;
      document.getElementById("whisper-label").textContent =
        whisper.enabled ? "Whisper on" : "Whisper off";
      const svc = whisper.services || {{}};
      const parts = Object.entries(svc).map(([k, v]) => `${{k.split("-").pop()}}: ${{v}}`);
      if (whisper.translate_engine && whisper.translate_engine !== "off") {{
        const src = whisper.language || "auto";
        const tgt = whisper.target_language || "en";
        parts.push(`translate: ${{whisper.translate_engine}} (${{src}}→${{tgt}})`);
      }}
      document.getElementById("whisper-detail").textContent = parts.join(" · ") || "—";
    }}

    whisperToggle.addEventListener("change", async () => {{
      if (whisperBusy) return;
      whisperBusy = true;
      whisperToggle.disabled = true;
      const enabled = whisperToggle.checked;
      try {{
        const res = await fetch("/api/whisper/enabled", {{
          method: "PUT",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{ enabled }}),
        }});
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "toggle failed");
        renderWhisper(data);
        showToast(enabled ? "Whisper started" : "Whisper stopped");
      }} catch (err) {{
        whisperToggle.checked = !enabled;
        showToast(err.message || "Whisper toggle failed");
      }} finally {{
        whisperBusy = false;
        whisperToggle.disabled = false;
      }}
    }});

    async function purgeWhisperQueue(hostId) {{
      if (purgeBusy) return;
      const path = hostId ? `/api/offload/${{hostId}}/purge-queue` : "/api/whisper/purge-queue";
      if (!confirm("Purge all pending audio chunks?\\n\\nRemoves untranscribed .wav/.mp3 on Pi5 and the offload host. Finished transcript audit files (.txt, .done) are kept.")) {{
        return;
      }}
      purgeBusy = true;
      if (whisperPurgeBtn) whisperPurgeBtn.disabled = true;
      document.querySelectorAll(".offload-purge").forEach(btn => {{ btn.disabled = true; }});
      try {{
        const res = await fetch(path, {{ method: "POST" }});
        const data = await res.json().catch(() => ({{}}));
        if (!res.ok) throw new Error(data.detail || res.statusText);
        showToast(`Purged ${{data.pi5_deleted || 0}} on Pi5, ${{data.remote_deleted || 0}} on offload`);
        await loadOffload();
      }} catch (e) {{
        showToast("Purge failed: " + (e.message || e));
      }} finally {{
        purgeBusy = false;
        if (whisperPurgeBtn) whisperPurgeBtn.disabled = false;
        document.querySelectorAll(".offload-purge").forEach(btn => {{ btn.disabled = false; }});
      }}
    }}

    if (whisperPurgeBtn) {{
      whisperPurgeBtn.addEventListener("click", () => purgeWhisperQueue(null));
    }}

    function showToast(msg) {{
      toast.textContent = msg;
      toast.style.display = "block";
      setTimeout(() => {{ toast.style.display = "none"; }}, 2800);
    }}

    function modeButtons(modes, {{ sync = false, hostId = null, activeMode = "" }} = {{}}) {{
      return modes.map(m => {{
        const active = m.id === activeMode ? " active" : "";
        const cls = sync ? "sync" : "";
        const attr = sync ? `data-sync-mode="${{m.id}}"` : `data-host-mode="${{hostId}}" data-mode="${{m.id}}"`;
        return `<button type="button" class="${{cls}}${{active}}" ${{attr}}>
          <strong>${{m.label}}</strong></button>`;
      }}).join("");
    }}

    function setHostModeActive(hostId, modeId) {{
      const grid = document.querySelector(`.host-modes[data-host="${{hostId}}"]`);
      if (!grid) return;
      grid.querySelectorAll("button").forEach(btn =>
        btn.classList.toggle("active", btn.dataset.mode === modeId));
    }}

    function renderHost(host) {{
      const card = document.querySelector(`.badge[data-host="${{host.id}}"]`);
      if (card) {{
        card.textContent = host.online ? "online" : "offline";
        card.classList.toggle("online", host.online);
        card.classList.toggle("offline", !host.online);
      }}
      const section = document.querySelector(`.host-modes[data-host="${{host.id}}"]`)?.closest("section");
      if (!section || !host.state) return;
      section.querySelector('[data-field="mode"]').textContent = host.state.active_mode || "—";
      const mediaEl = section.querySelector('[data-field="media"]');
      mediaEl.textContent = host.state.media_path
        ? " · " + host.state.media_path.split("/").pop() : "";
      if (host.state.active_mode) {{
        setHostModeActive(host.id, host.state.active_mode);
      }}
    }}

    let refreshSeq = 0;
    const wallFireBusy = {{}};
    const wallFireMode = {{}};
    const FIRE_INTENSITY_LABELS = ["Night (dim)", "1 panel", "2 panels", "Full (3)"];
    const COLOR_ROTATE_LABELS = ["Off", "Slow", "Medium", "Fast"];
    const FIRE_SWATCH_RGB = {{
      orange: "#ff5a00", red: "#ff2800", yellow: "#ffc800",
      blue: "#2878ff", green: "#28ff50", purple: "#b428ff",
      cyan: "#00dcff", magenta: "#ff00b4", white: "#ffffff",
    }};

    function rgbToHex([r, g, b]) {{
      return "#" + [r, g, b].map(v => v.toString(16).padStart(2, "0")).join("");
    }}

    function updateWallFirePanels(hosts) {{
      for (const hostId of HOST_IDS) {{
        const panel = document.querySelector(`[data-fire-panel="${{hostId}}"]`);
        if (!panel) continue;
        const host = (hosts || []).find(h => h.id === hostId);
        const mode = host?.state?.active_mode;
        const isFire = mode === "flame" || mode === "lava";
        panel.style.display = isFire ? "" : "none";
        if (isFire) wallFireMode[hostId] = mode;
        const title = document.querySelector(`[data-fire-title="${{hostId}}"]`);
        if (title && isFire) {{
          title.textContent = (mode === "lava" ? "Lava" : "Flame") + " colors";
        }}
      }}
    }}

    async function loadWallFireConfig(hostId, modeId) {{
      const mode = modeId || wallFireMode[hostId] || "flame";
      const res = await fetch(`/api/hosts/${{hostId}}/mode/${{mode}}/config`);
      if (!res.ok) return null;
      return res.json();
    }}

    async function saveWallFireConfig(hostId, patch) {{
      const mode = wallFireMode[hostId] || "flame";
      const res = await fetch(`/api/hosts/${{hostId}}/mode/${{mode}}/config`, {{
        method: "PUT",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify(patch),
      }});
      if (!res.ok) throw new Error((await res.json().catch(() => ({{}}))).detail || "failed");
      return res.json();
    }}

    function renderWallFire(hostId, data) {{
      const sw = document.querySelector(`[data-fire-swatches="${{hostId}}"]`);
      const intEl = document.querySelector(`[data-fire-intensity="${{hostId}}"]`);
      const rotEl = document.querySelector(`[data-fire-rotate="${{hostId}}"]`);
      const stops = document.querySelector(`[data-fire-stops="${{hostId}}"]`);
      if (!sw || !data) return;
      const activePreset = data.preset || null;
      const modeLabel = wallFireMode[hostId] || data.profile || "flame";
      sw.innerHTML = (data.presets || Object.keys(FIRE_SWATCH_RGB)).map(name => {{
        const rgb = FIRE_SWATCH_RGB[name] || "#ff5a00";
        const active = name === activePreset ? " active" : "";
        return `<button type="button" class="flame-swatch${{active}}" data-preset="${{name}}"
                style="background:${{rgb}}" title="${{name}}"></button>`;
      }}).join("");
      sw.onclick = async (ev) => {{
        const btn = ev.target.closest(".flame-swatch");
        if (!btn || wallFireBusy[hostId]) return;
        wallFireBusy[hostId] = true;
        try {{
          const cfg = await saveWallFireConfig(hostId, {{ preset: btn.dataset.preset }});
          renderWallFire(hostId, cfg);
          showToast(`${{hostId}} ${{modeLabel}} → ${{btn.dataset.preset}}`);
        }} catch (e) {{
          showToast(String(e.message || e));
        }} finally {{
          wallFireBusy[hostId] = false;
        }}
      }};

      if (intEl) {{
        const activeIntensity = data.intensity ?? 0;
        const gain = data.output_gain != null ? ` · ${{Math.round(data.output_gain * 100)}}%` : "";
        intEl.innerHTML = FIRE_INTENSITY_LABELS.map((label, idx) =>
          `<button type="button" class="${{idx === activeIntensity ? "active" : ""}}" data-intensity="${{idx}}">${{label}}</button>`
        ).join("") + `<span class="hint" style="flex:1 1 100%;margin:0.2rem 0 0;font-size:0.75rem">${{data.height_px || "—"}}px${{gain}}</span>`;
        intEl.onclick = async (ev) => {{
          const btn = ev.target.closest("button[data-intensity]");
          if (!btn || wallFireBusy[hostId]) return;
          wallFireBusy[hostId] = true;
          try {{
            const cfg = await saveWallFireConfig(hostId, {{ intensity: Number(btn.dataset.intensity) }});
            renderWallFire(hostId, cfg);
            showToast(`${{hostId}} ${{modeLabel}} → ${{FIRE_INTENSITY_LABELS[cfg.intensity ?? 0]}}`);
          }} catch (e) {{
            showToast(String(e.message || e));
          }} finally {{
            wallFireBusy[hostId] = false;
          }}
        }};
      }}

      if (rotEl) {{
        const labels = data.color_rotate_labels || COLOR_ROTATE_LABELS;
        const active = data.color_rotate_speed ?? 0;
        rotEl.innerHTML = `<span class="hint" style="flex:1 1 100%;margin:0 0 0.15rem;font-size:0.75rem">Color cycle</span>` +
          labels.map((label, idx) =>
            `<button type="button" class="${{idx === active ? "active" : ""}}" data-rotate-speed="${{idx}}">${{label}}</button>`
          ).join("");
        rotEl.onclick = async (ev) => {{
          const btn = ev.target.closest("button[data-rotate-speed]");
          if (!btn || wallFireBusy[hostId]) return;
          wallFireBusy[hostId] = true;
          try {{
            const cfg = await saveWallFireConfig(hostId, {{ color_rotate_speed: Number(btn.dataset.rotateSpeed) }});
            renderWallFire(hostId, cfg);
            showToast(`${{hostId}} ${{modeLabel}} color cycle · ${{labels[cfg.color_rotate_speed ?? 0]}}`);
          }} catch (e) {{
            showToast(String(e.message || e));
          }} finally {{
            wallFireBusy[hostId] = false;
          }}
        }};
      }}

      if (stops) {{
        const stopDefs = [
          ["core", "Core"],
          ["mid", "Mid"],
          ["tip", "Tip"],
        ];
        stops.innerHTML = stopDefs.map(([key, label]) => `
          <label class="flame-stop">
            <span>${{label}}</span>
            <input type="color" data-stop="${{key}}" value="${{rgbToHex(data[key] || [255,90,0])}}">
          </label>`).join("");
        stops.querySelectorAll("input[data-stop]").forEach(inp => {{
          inp.addEventListener("change", async () => {{
            if (wallFireBusy[hostId]) return;
            wallFireBusy[hostId] = true;
            const hex = inp.value;
            const rgb = [parseInt(hex.slice(1,3),16), parseInt(hex.slice(3,5),16), parseInt(hex.slice(5,7),16)];
            try {{
              const patch = {{}};
              patch[inp.dataset.stop] = rgb;
              const cfg = await saveWallFireConfig(hostId, patch);
              renderWallFire(hostId, cfg);
              showToast(`${{hostId}} ${{modeLabel}} ${{inp.dataset.stop}} updated`);
            }} catch (e) {{
              showToast(String(e.message || e));
            }} finally {{
              wallFireBusy[hostId] = false;
            }}
          }});
        }});
      }}
    }}

    const wallStarBusy = {{}};
    const STAR_INTENSITY_LABELS = ["Night (dim)", "Cruise", "Fast", "Warp"];
    const STAR_PRESET_RGB = {{
      classic: "#c8d2ff", warm: "#ffb450", cool: "#50a0ff",
      neon: "#ff50ff", ember: "#ff6414", aurora: "#50dc80",
    }};

    function updateWallStarPanels(hosts) {{
      for (const hostId of HOST_IDS) {{
        const panel = document.querySelector(`[data-star-panel="${{hostId}}"]`);
        if (!panel) continue;
        const host = (hosts || []).find(h => h.id === hostId);
        panel.style.display = host?.state?.active_mode === "starfield" ? "" : "none";
      }}
    }}

    async function loadWallStarConfig(hostId) {{
      const res = await fetch(`/api/hosts/${{hostId}}/mode/starfield/config`);
      if (!res.ok) return null;
      return res.json();
    }}

    async function saveWallStarConfig(hostId, patch) {{
      const res = await fetch(`/api/hosts/${{hostId}}/mode/starfield/config`, {{
        method: "PUT",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify(patch),
      }});
      if (!res.ok) throw new Error((await res.json().catch(() => ({{}}))).detail || "failed");
      return res.json();
    }}

    function renderWallStar(hostId, data) {{
      const intEl = document.querySelector(`[data-star-intensity="${{hostId}}"]`);
      const modesEl = document.querySelector(`[data-star-modes="${{hostId}}"]`);
      const rotEl = document.querySelector(`[data-star-rotate="${{hostId}}"]`);
      const sw = document.querySelector(`[data-star-swatches="${{hostId}}"]`);
      const stops = document.querySelector(`[data-star-stops="${{hostId}}"]`);
      if (!data) return;
      if (intEl) {{
        const active = data.intensity ?? 0;
        const meta = `${{data.star_count || "—"}} · ${{data.speed || "—"}}x · ${{Math.round((data.output_gain || 0) * 100)}}%`;
        intEl.innerHTML = STAR_INTENSITY_LABELS.map((label, idx) =>
          `<button type="button" class="${{idx === active ? "active" : ""}}" data-intensity="${{idx}}">${{label}}</button>`
        ).join("") + `<span class="hint" style="flex:1 1 100%;margin:0.2rem 0 0;font-size:0.75rem">${{meta}}</span>`;
        intEl.onclick = async (ev) => {{
          const btn = ev.target.closest("button[data-intensity]");
          if (!btn || wallStarBusy[hostId]) return;
          wallStarBusy[hostId] = true;
          try {{
            renderWallStar(hostId, await saveWallStarConfig(hostId, {{ intensity: Number(btn.dataset.intensity) }}));
            showToast(`${{hostId}} starfield → ${{STAR_INTENSITY_LABELS[Number(btn.dataset.intensity)]}}`);
          }} catch (e) {{ showToast(String(e.message || e)); }}
          finally {{ wallStarBusy[hostId] = false; }}
        }};
      }}
      if (modesEl) {{
        const active = data.color_mode || "depth";
        const modes = data.color_modes || ["white","warm","cool","rainbow","depth","dual"];
        modesEl.innerHTML = modes.map(name =>
          `<button type="button" class="${{name === active ? "active" : ""}}" data-color-mode="${{name}}">${{name}}</button>`
        ).join("");
        modesEl.onclick = async (ev) => {{
          const btn = ev.target.closest("button[data-color-mode]");
          if (!btn || wallStarBusy[hostId]) return;
          wallStarBusy[hostId] = true;
          try {{
            renderWallStar(hostId, await saveWallStarConfig(hostId, {{ color_mode: btn.dataset.colorMode }}));
            showToast(`${{hostId}} color · ${{btn.dataset.colorMode}}`);
          }} catch (e) {{ showToast(String(e.message || e)); }}
          finally {{ wallStarBusy[hostId] = false; }}
        }};
      }}
      if (rotEl) {{
        const labels = data.color_rotate_labels || COLOR_ROTATE_LABELS;
        const active = data.color_rotate_speed ?? 0;
        rotEl.innerHTML = `<span class="hint" style="flex:1 1 100%;margin:0 0 0.15rem;font-size:0.75rem">Color cycle</span>` +
          labels.map((label, idx) =>
            `<button type="button" class="${{idx === active ? "active" : ""}}" data-rotate-speed="${{idx}}">${{label}}</button>`
          ).join("");
        rotEl.onclick = async (ev) => {{
          const btn = ev.target.closest("button[data-rotate-speed]");
          if (!btn || wallStarBusy[hostId]) return;
          wallStarBusy[hostId] = true;
          try {{
            renderWallStar(hostId, await saveWallStarConfig(hostId, {{ color_rotate_speed: Number(btn.dataset.rotateSpeed) }}));
            showToast(`${{hostId}} starfield color cycle · ${{labels[Number(btn.dataset.rotateSpeed)]}}`);
          }} catch (e) {{ showToast(String(e.message || e)); }}
          finally {{ wallStarBusy[hostId] = false; }}
        }};
      }}
      if (sw) {{
        const activePreset = data.preset || null;
        sw.innerHTML = (data.presets || Object.keys(STAR_PRESET_RGB)).map(name => {{
          const rgb = STAR_PRESET_RGB[name] || "#ffffff";
          const active = name === activePreset ? " active" : "";
          return `<button type="button" class="flame-swatch${{active}}" data-preset="${{name}}"
                  style="background:${{rgb}}" title="${{name}}"></button>`;
        }}).join("");
        sw.onclick = async (ev) => {{
          const btn = ev.target.closest(".flame-swatch");
          if (!btn || wallStarBusy[hostId]) return;
          wallStarBusy[hostId] = true;
          try {{
            renderWallStar(hostId, await saveWallStarConfig(hostId, {{ preset: btn.dataset.preset }}));
            showToast(`${{hostId}} starfield → ${{btn.dataset.preset}}`);
          }} catch (e) {{ showToast(String(e.message || e)); }}
          finally {{ wallStarBusy[hostId] = false; }}
        }};
      }}
      if (stops) {{
        const defs = [["near","Near"],["mid","Mid"],["far","Far"]];
        stops.innerHTML = defs.map(([key, label]) => `
          <label class="flame-stop">
            <span>${{label}}</span>
            <input type="color" data-stop="${{key}}" value="${{rgbToHex(data[key] || [255,255,255])}}">
          </label>`).join("");
        stops.querySelectorAll("input[data-stop]").forEach(inp => {{
          inp.addEventListener("change", async () => {{
            if (wallStarBusy[hostId]) return;
            wallStarBusy[hostId] = true;
            const hex = inp.value;
            const rgb = [parseInt(hex.slice(1,3),16), parseInt(hex.slice(3,5),16), parseInt(hex.slice(5,7),16)];
            try {{
              const patch = {{}};
              patch[inp.dataset.stop] = rgb;
              renderWallStar(hostId, await saveWallStarConfig(hostId, patch));
              showToast(`${{hostId}} star ${{inp.dataset.stop}} updated`);
            }} catch (e) {{ showToast(String(e.message || e)); }}
            finally {{ wallStarBusy[hostId] = false; }}
          }});
        }});
      }}
    }}

    const wallRainBusy = {{}};

    function updateWallRainPanels(hosts) {{
      for (const hostId of HOST_IDS) {{
        const panel = document.querySelector(`[data-rain-panel="${{hostId}}"]`);
        if (!panel) continue;
        const host = (hosts || []).find(h => h.id === hostId);
        panel.style.display = host?.state?.active_mode === "matrix_rain" ? "" : "none";
      }}
    }}

    async function loadWallRainConfig(hostId) {{
      const res = await fetch(`/api/hosts/${{hostId}}/mode/matrix_rain/config`);
      return res.ok ? res.json() : null;
    }}

    async function saveWallRain(hostId, patch, label) {{
      if (wallRainBusy[hostId]) return;
      wallRainBusy[hostId] = true;
      try {{
        const res = await fetch(`/api/hosts/${{hostId}}/mode/matrix_rain/config`, {{
          method: "PUT",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify(patch),
        }});
        if (!res.ok) throw new Error((await res.json().catch(() => ({{}}))).detail || "failed");
        renderWallRain(hostId, await res.json());
        showToast(`${{hostId}} matrix rain · ${{label}}`);
      }} catch (e) {{ showToast(String(e.message || e)); }}
      finally {{ wallRainBusy[hostId] = false; }}
    }}

    function renderWallRain(hostId, data) {{
      if (!data) return;
      const speedEl = document.querySelector(`[data-rain-speed="${{hostId}}"]`);
      const sw = document.querySelector(`[data-rain-swatches="${{hostId}}"]`);
      const colorEl = document.querySelector(`[data-rain-color="${{hostId}}"]`);
      speedEl.innerHTML = (data.speed_labels || []).map((label, idx) =>
        `<button type="button" class="${{idx === data.speed ? "active" : ""}}" data-speed="${{idx}}">${{label}}</button>`
      ).join("");
      speedEl.onclick = (ev) => {{
        const btn = ev.target.closest("button[data-speed]");
        if (btn) saveWallRain(hostId, {{ speed: Number(btn.dataset.speed) }}, btn.textContent);
      }};
      sw.innerHTML = Object.entries(data.presets || {{}}).map(([name, rgb]) =>
        `<button type="button" class="flame-swatch${{name === data.preset ? " active" : ""}}" data-preset="${{name}}"
                style="background:${{rgbToHex(rgb)}}" title="${{name}}"></button>`
      ).join("");
      sw.onclick = (ev) => {{
        const btn = ev.target.closest(".flame-swatch");
        if (btn) saveWallRain(hostId, {{ preset: btn.dataset.preset }}, btn.dataset.preset);
      }};
      colorEl.value = rgbToHex(data.color || [0, 255, 70]);
      colorEl.onchange = () => {{
        const hex = colorEl.value;
        const rgb = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16));
        saveWallRain(hostId, {{ color: rgb }}, hex);
      }};
    }}

{EFFECT_JS}
    const wallEffectBusy = {{}};

    function updateWallEffectPanels(hosts) {{
      for (const hostId of HOST_IDS) {{
        const panel = document.querySelector(`[data-effect-panel="${{hostId}}"]`);
        if (!panel) continue;
        const host = (hosts || []).find(h => h.id === hostId);
        panel.style.display = EFFECT_MODES.includes(host?.state?.active_mode) ? "" : "none";
      }}
    }}

    function renderWallEffect(hostId, mode, cfg) {{
      if (!cfg) return;
      document.querySelector(`[data-effect-title="${{hostId}}"]`).textContent = cfg.title;
      renderEffectPanel(document.querySelector(`[data-effect-controls="${{hostId}}"]`), cfg,
        (patch, label) => saveWallEffect(hostId, mode, patch, label));
    }}

    async function loadWallEffect(hostId, mode) {{
      const res = await fetch(`/api/hosts/${{hostId}}/mode/${{mode}}/effect`);
      if (res.ok) renderWallEffect(hostId, mode, await res.json());
    }}

    async function saveWallEffect(hostId, mode, patch, label) {{
      if (wallEffectBusy[hostId]) return;
      wallEffectBusy[hostId] = true;
      try {{
        const res = await fetch(`/api/hosts/${{hostId}}/mode/${{mode}}/effect`, {{
          method: "PUT",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify(patch),
        }});
        const data = await res.json().catch(() => ({{}}));
        if (!res.ok) throw new Error(data.detail || "failed");
        renderWallEffect(hostId, mode, data);
        showToast(`${{hostId}} ${{data.title.toLowerCase()}} · ${{label}}`);
      }} catch (e) {{ showToast(String(e.message || e)); }}
      finally {{ wallEffectBusy[hostId] = false; }}
    }}

    async function loadModes() {{
      const res = await fetch("/api/modes");
      if (!res.ok) throw new Error("modes unavailable");
      return res.json();
    }}

    async function refresh() {{
      const seq = ++refreshSeq;
      try {{
        const [health, modes] = await Promise.all([
          fetch("/api/health").then(r => r.json()),
          loadModes().catch(() => []),
        ]);
        if (seq !== refreshSeq) return;
        const online = health.hosts_online ?? 0;
        const total = health.hosts_total ?? HOST_IDS.length;
        document.getElementById("health-summary").innerHTML =
          `<strong>${{online}}/${{total}}</strong> walls online · Whisper ${{
            health.whisper?.enabled ? "on" : "off"
          }} · auto-refresh 15s`;

        if (health.whisper) renderWhisper(health.whisper);

        if (modes.length) {{
          const syncGrid = document.getElementById("sync-modes");
          if (!syncGrid.dataset.ready) {{
            syncGrid.innerHTML = modeButtons(modes, {{ sync: true }});
            syncGrid.dataset.ready = "1";
            syncGrid.querySelectorAll("[data-sync-mode]").forEach(btn => {{
              btn.addEventListener("click", async () => {{
                const mode = btn.dataset.syncMode;
                const res = await fetch(`/api/sync/mode/${{mode}}`, {{ method: "PUT" }});
                const data = await res.json();
                if (!res.ok) {{ showToast("Failed"); return; }}
                for (const host of data.results || []) {{
                  renderHost(host);
                }}
                showToast(data.all_ok ? `Both → ${{mode}}` : "Some hosts failed");
                await refresh();
              }});
            }});
          }}
          for (const hostId of HOST_IDS) {{
            const grid = document.querySelector(`.host-modes[data-host="${{hostId}}"]`);
            if (grid && !grid.dataset.ready) {{
              const hostInfo = (health.hosts || []).find(h => h.id === hostId);
              grid.innerHTML = modeButtons(modes, {{
                hostId,
                activeMode: hostInfo?.state?.active_mode || "",
              }});
              grid.dataset.ready = "1";
              grid.querySelectorAll("[data-host-mode]").forEach(btn => {{
                btn.addEventListener("click", async () => {{
                  const id = btn.dataset.hostMode;
                  const mode = btn.dataset.mode;
                  setHostModeActive(id, mode);
                  const res = await fetch(`/api/hosts/${{id}}/mode/${{mode}}`, {{ method: "PUT" }});
                  const data = await res.json().catch(() => null);
                  if (!res.ok) {{
                    showToast(data?.detail || "Failed");
                    await refresh();
                    return;
                  }}
                  renderHost(data);
                  showToast(`${{id}} → ${{mode}}`);
                  await refresh();
                }});
              }});
            }}
          }}
        }}

        if (seq !== refreshSeq) return;

        for (const host of health.hosts || []) {{
          renderHost(host);
        }}

        updateWallFirePanels(health.hosts);
        updateWallStarPanels(health.hosts);
        updateWallRainPanels(health.hosts);
        updateWallEffectPanels(health.hosts);
        for (const hostId of HOST_IDS) {{
          const host = (health.hosts || []).find(h => h.id === hostId);
          const mode = host?.state?.active_mode;
          if (EFFECT_MODES.includes(mode)) {{
            loadWallEffect(hostId, mode).catch(e => console.error(e));
          }}
          if (mode === "matrix_rain") {{
            try {{
              renderWallRain(hostId, await loadWallRainConfig(hostId));
            }} catch (e) {{
              console.error(e);
            }}
          }}
          if (mode === "flame" || mode === "lava") {{
            try {{
              const cfg = await loadWallFireConfig(hostId, mode);
              if (cfg) renderWallFire(hostId, cfg);
            }} catch (e) {{
              console.error(e);
            }}
          }}
          if (mode === "starfield") {{
            try {{
              const cfg = await loadWallStarConfig(hostId);
              if (cfg) renderWallStar(hostId, cfg);
            }} catch (e) {{
              console.error(e);
            }}
          }}
        }}

        for (const hostId of HOST_IDS) {{
          if (seq !== refreshSeq) return;
          const list = document.querySelector(`[data-media="${{hostId}}"]`);
          if (!list) continue;
          try {{
            const res = await fetch(`/api/hosts/${{hostId}}/media`);
            if (!res.ok) {{ list.innerHTML = "<em>Unavailable</em>"; continue; }}
            const files = await res.json();
            if (!files.length) {{ list.innerHTML = "<em>No media files</em>"; continue; }}
            list.innerHTML = files.map(f => `
              <button type="button" class="media-btn" data-host="${{hostId}}" data-path="${{f.path.replace(/"/g, "&quot;")}}">
                <strong>${{f.name}}</strong><span>${{f.kind}}</span>
              </button>`).join("");
            list.querySelectorAll(".media-btn").forEach(btn => {{
              btn.addEventListener("click", async () => {{
                const res = await fetch(`/api/hosts/${{btn.dataset.host}}/media`, {{
                  method: "PUT",
                  headers: {{ "Content-Type": "application/json" }},
                  body: JSON.stringify({{ path: btn.dataset.path }}),
                }});
                if (!res.ok) {{ showToast("Media failed"); return; }}
                showToast("Playing on " + btn.dataset.host);
                await refresh();
              }});
            }});
          }} catch (e) {{
            list.innerHTML = "<em>Unavailable</em>";
          }}
        }}
      }} catch (err) {{
        document.getElementById("health-summary").textContent = "Could not reach orchestrator API";
        console.error(err);
      }}
    }}

    document.getElementById("refresh").addEventListener("click", refresh);
    document.getElementById("mqtt-purge").addEventListener("click", async (e) => {{
      if (!confirm("Purge MQTT everywhere?\\n\\nDrops untranscribed Whisper audio on Pi5 and the offload host, clears retained broker topics, and clears captions on every wall. Custom messages are not affected.")) return;
      const btn = e.currentTarget;
      btn.disabled = true;
      try {{
        const res = await fetch("/api/mqtt/purge", {{ method: "POST" }});
        const d = await res.json();
        const w = d.whisper || {{}};
        const parts = [
          w.error ? `Whisper: ${{w.error}}` : `Whisper: ${{(w.pi5_deleted || 0) + (w.remote_deleted || 0)}} chunks dropped`,
          d.retained_error || `${{(d.retained_cleared || []).length}} retained topics cleared`,
          ...(d.walls || []).map(h => `${{h.label}}: ${{h.online ? "cleared" : "unreachable"}}`),
        ];
        showToast((d.ok ? "Purged — " : "Purge incomplete — ") + parts.join(" · "));
      }} catch (err) {{
        showToast("Purge failed: " + err.message);
      }} finally {{
        btn.disabled = false;
      }}
    }});

    document.getElementById("mqtt-test").addEventListener("click", async () => {{
      const res = await fetch("/api/mqtt/test", {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{ text: "Orchestrator MQTT test", ttl: 12, color: [0, 255, 120] }}),
      }});
      showToast(res.ok ? "MQTT test sent" : "MQTT test failed");
    }});

    function fmtAge(s) {{
      if (s < 60) return s + "s ago";
      if (s < 3600) return Math.round(s / 60) + "m ago";
      return Math.round(s / 3600) + "h ago";
    }}

    async function loadOffload() {{
      const section = document.getElementById("offload-section");
      const grid = document.getElementById("offload-grid");
      try {{
        const res = await fetch("/api/offload");
        if (!res.ok) return;
        const hosts = await res.json();
        if (!hosts.length) {{ section.style.display = "none"; return; }}
        section.style.display = "";
        grid.innerHTML = hosts.map(h => {{
          const badge = h.online ? '<span class="chip ok">online</span>'
            : (h.reachable ? '<span class="chip warn">degraded</span>'
                           : '<span class="chip bad">offline</span>');
          const fwd = `<span class="chip ${{h.forwarder === "active" ? "ok" : "bad"}}">forward: ${{h.forwarder}}</span>`;
          const tr = `<span class="chip ${{h.transcribe === "active" ? "ok" : (h.reachable ? "bad" : "warn")}}">transcribe: ${{h.transcribe}}</span>`;
          const model = h.model ? `<span class="chip">model: ${{h.model}}</span>` : "";
          const age = (h.last_caption_age_sec !== null && h.last_caption_age_sec !== undefined)
            ? `<span class="chip ${{h.last_caption_age_sec < 120 ? "ok" : "warn"}}">last caption: ${{fmtAge(h.last_caption_age_sec)}}</span>` : "";
          const pend = (h.pending_chunks !== null && h.pending_chunks !== undefined)
            ? `<span class="chip ${{h.pending_chunks === 0 ? "ok" : "warn"}}">queue: ${{h.pending_chunks}}</span>` : "";
          const err = h.error ? `<span class="chip bad">${{h.error}}</span>` : "";
          return `<div class="offload-card" data-offload-id="${{h.id}}">
            <h3><span>${{h.label}} <span style="color:#6b7280;font-weight:400">${{h.host}}</span></span>${{badge}}</h3>
            <div class="chips">${{fwd}}${{tr}}${{model}}${{pend}}${{age}}${{err}}</div>
            <div class="offload-actions">
              <button type="button" class="offload-purge" data-offload-id="${{h.id}}">Purge queue</button>
            </div>
          </div>`;
        }}).join("");
        grid.querySelectorAll(".offload-purge").forEach(btn => {{
          btn.addEventListener("click", () => purgeWhisperQueue(btn.dataset.offloadId));
        }});
      }} catch (e) {{
        console.error(e);
      }}
    }}

    const wallMqttBusy = {{}};

    function renderWallMqtt(hostId, data) {{
      const box = document.querySelector(`[data-sources="${{hostId}}"]`);
      const master = document.querySelector(`.wall-mqtt-master[data-host="${{hostId}}"]`);
      if (!box || !master) return;
      master.checked = !!data.overlay_enabled;
      const srcs = data.sources || [];
      if (!srcs.length) {{ box.innerHTML = "<em>No MQTT sources for this wall</em>"; return; }}
      const on = data.overlay_enabled;
      box.innerHTML = srcs.map(s => `
        <label class="src-check ${{on ? "" : "disabled"}}">
          <input type="checkbox" data-host="${{hostId}}" data-source="${{s.id}}" ${{s.enabled ? "checked" : ""}} ${{on ? "" : "disabled"}}>
          <span>${{s.label}}</span>
        </label>`).join("");
      box.querySelectorAll("input[data-source]").forEach(cb => {{
        cb.addEventListener("change", () => {{
          const sources = {{}};
          sources[cb.dataset.source] = cb.checked;
          saveWallMqtt(hostId, {{ sources }});
        }});
      }});
    }}

    async function saveWallMqtt(hostId, patch) {{
      if (wallMqttBusy[hostId]) return;
      wallMqttBusy[hostId] = true;
      try {{
        const res = await fetch(`/api/hosts/${{hostId}}/mqtt`, {{
          method: "PUT",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify(patch),
        }});
        const data = await res.json().catch(() => null);
        if (!res.ok) throw new Error((data && data.detail) || "MQTT update failed");
        renderWallMqtt(hostId, data);
        showToast("MQTT updated on " + hostId);
      }} catch (err) {{
        showToast(err.message || "MQTT update failed");
        loadWallMqtt(hostId);
      }} finally {{
        wallMqttBusy[hostId] = false;
      }}
    }}

    async function loadWallMqtt(hostId) {{
      const box = document.querySelector(`[data-sources="${{hostId}}"]`);
      if (!box) return;
      try {{
        const res = await fetch(`/api/hosts/${{hostId}}/mqtt`);
        if (!res.ok) {{ box.innerHTML = "<em>Unavailable</em>"; return; }}
        renderWallMqtt(hostId, await res.json());
      }} catch (e) {{
        box.innerHTML = "<em>Unavailable</em>";
      }}
    }}

    document.querySelectorAll(".wall-mqtt-master").forEach(m => {{
      m.addEventListener("change", () => saveWallMqtt(m.dataset.host, {{ overlay_enabled: m.checked }}));
    }});
    HOST_IDS.forEach(loadWallMqtt);
{MESSAGES_JS}
    refresh();
    loadOffload();
    setInterval(refresh, 15000);
    setInterval(loadOffload, 15000);
  </script>
</body>
</html>"""


def create_app() -> FastAPI:
    return app
