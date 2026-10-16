"""FastAPI control panel for the LED matrix display."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import Body, FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from display.brightness import BrightnessSchedule
from display.media_library import list_media_files
from display.messages.schedule import current_showing, next_showing
from display.messages.schema import MessageError
from display.messages.store import (
    clear_preview,
    load_preview,
    load_state as load_message_state,
    save_messages,
    set_preview,
)
from display.modes.effect_config import EFFECT_MODE_IDS, effect_config_for_api, validate_effect_patch
from display.modes.flame_config import (
    FLAME_PRESETS,
    flame_config_for_api,
    lava_config_for_api,
)
from display.modes.matrix_rain_config import (
    MAX_SPEED as RAIN_MAX_SPEED,
    RAIN_PRESETS,
    matrix_rain_config_for_api,
)
from display.modes.starfield_config import (
    COLOR_MODES,
    STARFIELD_PRESETS,
    starfield_config_for_api,
)
from display.modes.registry import MODES, list_modes
from display.mqtt.overlay import load_mqtt_config
from display.mqtt.purge import request_purge as request_mqtt_purge
from display.mqtt.settings import load_overlay_settings, update_overlay_settings
from display.mqtt.sources import SOURCE_CATALOG, wall_source_ids
from display.state import load_state, set_active_mode, set_media_path, set_mode_config
from web.effect_ui import EFFECT_CSS, EFFECT_JS

app = FastAPI(title="Spectra Matrix Controller", version="0.2.0")


class ModeSummary(BaseModel):
    id: str
    label: str
    description: str


class MediaFileSummary(BaseModel):
    path: str
    name: str
    kind: str
    folder: str


class StateResponse(BaseModel):
    active_mode: str
    media_path: Optional[str] = None
    mode_config: Optional[dict] = None
    updated_at: float | None
    modes: List[ModeSummary]


class FireConfigResponse(BaseModel):
    profile: Optional[str] = None
    preset: Optional[str] = None
    intensity: int = 0
    panel_rows: int = 3
    height_px: int = 0
    output_gain: float = 1.0
    damping: float = 0.97
    core: List[int]
    mid: List[int]
    tip: List[int]
    ember: List[int]
    colors: List[List[int]]
    presets: List[str]
    color_rotate_speed: int = 0
    color_rotate_labels: List[str] = []
    color_rotate_hz: float = 0.0


class FireConfigRequest(BaseModel):
    preset: Optional[str] = None
    intensity: Optional[int] = None
    core: Optional[List[int]] = None
    mid: Optional[List[int]] = None
    tip: Optional[List[int]] = None
    ember: Optional[List[int]] = None
    color_rotate_speed: Optional[int] = None


class StarfieldConfigResponse(BaseModel):
    preset: Optional[str] = None
    color_mode: str = "depth"
    color_modes: List[str]
    intensity: int = 0
    panel_rows: int = 3
    star_count: int = 0
    speed: float = 1.0
    output_gain: float = 1.0
    near: List[int]
    mid: List[int]
    far: List[int]
    presets: List[str]
    color_rotate_speed: int = 0
    color_rotate_labels: List[str] = []
    color_rotate_hz: float = 0.0


class StarfieldConfigRequest(BaseModel):
    preset: Optional[str] = None
    color_mode: Optional[str] = None
    intensity: Optional[int] = None
    near: Optional[List[int]] = None
    mid: Optional[List[int]] = None
    far: Optional[List[int]] = None
    color_rotate_speed: Optional[int] = None


class MatrixRainConfigResponse(BaseModel):
    preset: Optional[str] = None
    color: List[int]
    presets: Dict[str, List[int]]
    speed: int = 1
    speed_labels: List[str]


class MatrixRainConfigRequest(BaseModel):
    preset: Optional[str] = None
    color: Optional[List[int]] = None
    speed: Optional[int] = None


# Back-compat aliases for older imports / mental model.
FlameConfigResponse = FireConfigResponse
FlameConfigRequest = FireConfigRequest


class MediaSelectRequest(BaseModel):
    path: str = Field(..., min_length=1)


class MqttSourceState(BaseModel):
    id: str
    label: str
    enabled: bool
    topics: List[str]


class MqttOverlayResponse(BaseModel):
    overlay_enabled: bool
    sources: List[MqttSourceState]
    subscribed_topics: List[str]


class MqttOverlayUpdateRequest(BaseModel):
    overlay_enabled: Optional[bool] = None
    sources: Optional[dict[str, bool]] = None


def _mqtt_subscribed_topics() -> List[str]:
    return list(load_mqtt_config().get("topics") or [])


def _mqtt_overlay_response() -> MqttOverlayResponse:
    topics = _mqtt_subscribed_topics()
    settings = load_overlay_settings(topics)
    wall_ids = wall_source_ids(topics)
    sources = [
        MqttSourceState(
            id=sid,
            label=str(SOURCE_CATALOG[sid]["label"]),
            enabled=settings.source_enabled(sid),
            topics=[str(t) for t in SOURCE_CATALOG[sid].get("topics") or ()],
        )
        for sid in wall_ids
        if sid in SOURCE_CATALOG
    ]
    return MqttOverlayResponse(
        overlay_enabled=settings.overlay_enabled,
        sources=sources,
        subscribed_topics=topics,
    )


@app.get("/", response_class=HTMLResponse)
def control_panel() -> str:
    state = load_state()
    cards = []
    for info in list_modes():
        active = " active" if info.id == state.active_mode else ""
        cards.append(
            f"""
            <button class="mode-btn{active}" data-mode="{info.id}" type="button">
              <strong>{info.label}</strong>
              <span>{info.description}</span>
            </button>
            """
        )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Spectra Matrix Display</title>
  <style>
    :root {{
      color-scheme: dark;
      font-family: system-ui, sans-serif;
      background: #0f1115;
      color: #e8eaed;
    }}
    body {{ max-width: 42rem; margin: 2rem auto; padding: 0 1rem 3rem; }}
    h1 {{ font-size: 1.4rem; margin-bottom: 0.25rem; }}
    h2 {{ font-size: 1rem; margin: 1.75rem 0 0.75rem; color: #9aa0a6; font-weight: 600; }}
    .status {{ color: #9aa0a6; margin-bottom: 1.5rem; }}
    .grid {{ display: grid; gap: 0.75rem; }}
    .mode-btn, .media-btn {{
      display: block; width: 100%; text-align: left;
      background: #1a1d24; border: 1px solid #30343c;
      border-radius: 10px; padding: 0.85rem 1rem; cursor: pointer; color: inherit;
    }}
    .mode-btn:hover, .media-btn:hover {{ border-color: #5f9cff; }}
    .mode-btn.active, .media-btn.active {{ border-color: #5f9cff; background: #152033; }}
    .mode-btn strong, .media-btn strong {{ display: block; margin-bottom: 0.25rem; }}
    .mode-btn span {{ color: #9aa0a6; font-size: 0.9rem; }}
    .media-btn span {{ color: #6b7280; font-size: 0.8rem; margin-left: 0.5rem; }}
    .media-list {{ display: grid; gap: 0.5rem; max-height: 24rem; overflow-y: auto; }}
    .hint {{ color: #6b7280; font-size: 0.85rem; margin-bottom: 0.75rem; }}
    .mqtt-panel {{
      background: #1a1d24; border: 1px solid #30343c; border-radius: 10px;
      padding: 1rem; margin-top: 0.5rem;
    }}
    .mqtt-row {{
      display: flex; align-items: center; justify-content: space-between;
      gap: 1rem; padding: 0.5rem 0; border-bottom: 1px solid #252830;
    }}
    .mqtt-row:last-child {{ border-bottom: none; }}
    .switch {{
      position: relative; width: 2.75rem; height: 1.5rem; flex-shrink: 0;
    }}
    .switch input {{ opacity: 0; width: 0; height: 0; }}
    .slider {{
      position: absolute; inset: 0; cursor: pointer; background: #3a3f4b;
      border-radius: 999px; transition: 0.2s;
    }}
    .slider:before {{
      content: ""; position: absolute; height: 1.1rem; width: 1.1rem;
      left: 0.2rem; bottom: 0.2rem; background: #e8eaed; border-radius: 50%;
      transition: 0.2s;
    }}
    .switch input:checked + .slider {{ background: #3d7eff; }}
    .switch input:checked + .slider:before {{ transform: translateX(1.25rem); }}
    .source-check {{
      display: flex; align-items: center; gap: 0.5rem; cursor: pointer;
      font-size: 0.95rem;
    }}
    .source-check input {{ width: 1rem; height: 1rem; accent-color: #5f9cff; }}
    .source-topics {{ color: #6b7280; font-size: 0.75rem; display: block; margin-top: 0.15rem; }}
    #toast {{
      position: fixed; bottom: 1rem; right: 1rem;
      background: #1e3a2f; border: 1px solid #3d9970;
      padding: 0.75rem 1rem; border-radius: 8px; display: none;
    }}
    .flame-panel {{
      background: #1a1d24; border: 1px solid #30343c; border-radius: 10px;
      padding: 1rem; margin-top: 0.75rem;
    }}
    .flame-swatches {{ display: flex; flex-wrap: wrap; gap: 0.5rem; margin-top: 0.5rem; }}
    .flame-swatch {{
      width: 2.25rem; height: 2.25rem; border-radius: 8px; border: 2px solid #30343c;
      cursor: pointer; padding: 0;
    }}
    .flame-swatch.active {{ border-color: #5f9cff; box-shadow: 0 0 0 1px #5f9cff; }}
    .flame-swatch span {{ position: absolute; width: 1px; height: 1px; overflow: hidden; }}
    .flame-stops {{ display: grid; gap: 0.45rem; margin-top: 0.65rem; }}
    .flame-stop {{ display: flex; align-items: center; justify-content: space-between; gap: 0.75rem; font-size: 0.9rem; }}
    .flame-stop input[type=color] {{ width: 2.5rem; height: 1.75rem; border: 1px solid #30343c; border-radius: 6px; background: #0f1115; cursor: pointer; padding: 0; }}
    .flame-intensity {{ display: flex; flex-wrap: wrap; gap: 0.4rem; margin-top: 0.65rem; }}
    .flame-intensity button {{
      flex: 1 1 auto; min-width: 4.5rem; text-align: center; padding: 0.45rem 0.5rem;
      background: #1a1d24; border: 1px solid #30343c; border-radius: 8px; color: inherit; cursor: pointer; font-size: 0.82rem;
    }}
    .flame-intensity button.active {{ border-color: #5f9cff; background: #152033; }}
{EFFECT_CSS}
  </style>
</head>
<body>
  <h1>Spectra Matrix Display</h1>
  <p class="status">
    Active mode: <strong id="active-mode">{state.active_mode}</strong>
    <span id="active-media"></span>
  </p>
  <div class="grid mode-grid">
    {"".join(cards)}
  </div>

  <div class="flame-panel" id="fire-panel" style="display:none">
    <h2 id="fire-panel-title" style="margin:0 0 0.35rem;font-size:1rem;color:#e8eaed">Fire colors</h2>
    <p class="hint" id="fire-panel-hint" style="margin:0">Preset themes or tune core / mid / tip (this display only).</p>
    <div class="flame-swatches" id="fire-swatches"><em>Loading…</em></div>
    <div class="flame-intensity" id="fire-intensity"></div>
    <div class="flame-intensity" id="fire-rotate" style="margin-top:0.45rem"></div>
    <div class="flame-stops" id="fire-stops"></div>
  </div>

  <div class="flame-panel" id="starfield-panel" style="display:none">
    <h2 style="margin:0 0 0.35rem;font-size:1rem;color:#e8eaed">Starfield</h2>
    <p class="hint" style="margin:0">Win95-style fly-through. Night = sparse &amp; dim. Color mode + palette (this display only).</p>
    <div class="flame-intensity" id="star-intensity"></div>
    <div class="flame-intensity" id="star-color-modes" style="margin-top:0.45rem"></div>
    <div class="flame-intensity" id="star-rotate" style="margin-top:0.45rem"></div>
    <div class="flame-swatches" id="star-swatches"><em>Loading…</em></div>
    <div class="flame-stops" id="star-stops"></div>
  </div>

  <div class="flame-panel" id="rain-panel" style="display:none">
    <h2 style="margin:0 0 0.35rem;font-size:1rem;color:#e8eaed">Matrix rain</h2>
    <p class="hint" style="margin:0">Preset or any custom color, plus speed (this display only).</p>
    <div class="flame-intensity" id="rain-speed"></div>
    <div class="flame-swatches" id="rain-swatches"><em>Loading…</em></div>
    <div class="flame-stops">
      <label class="flame-stop">
        <span>Custom color</span>
        <input type="color" id="rain-color" value="#00ff46">
      </label>
    </div>
  </div>

  <div class="flame-panel" id="effect-panel" style="display:none">
    <h2 id="effect-title" style="margin:0 0 0.35rem;font-size:1rem;color:#e8eaed"></h2>
    <p class="hint" id="effect-hint" style="margin:0"></p>
    <div id="effect-controls"></div>
  </div>

  <h2>Animations &amp; videos</h2>
  <p class="hint">Select a file to switch to media mode and play full-screen on the panel.</p>
  <div class="media-list" id="media-list"><em>Loading…</em></div>

  <h2>MQTT overlay</h2>
  <p class="hint">Toggle live MQTT captions on <strong>this display only</strong>. Choose which feeds to show.</p>
  <div class="mqtt-panel" id="mqtt-panel">
    <div class="mqtt-row">
      <div>
        <strong>Show MQTT on this display</strong>
        <span class="source-topics">When off, scheduled modes continue uninterrupted.</span>
      </div>
      <label class="switch" title="MQTT overlay master toggle">
        <input type="checkbox" id="mqtt-master" />
        <span class="slider"></span>
      </label>
    </div>
    <div id="mqtt-sources"><em>Loading sources…</em></div>
  </div>

  <div id="toast"></div>
  <script>
    const toast = document.getElementById("toast");
    const activeEl = document.getElementById("active-mode");
    const activeMediaEl = document.getElementById("active-media");
    let currentMediaPath = {json.dumps(state.media_path)};

    function showToast(msg) {{
      toast.textContent = msg;
      toast.style.display = "block";
      setTimeout(() => {{ toast.style.display = "none"; }}, 2500);
    }}

    function updateMediaHighlight(path) {{
      currentMediaPath = path;
      document.querySelectorAll(".media-btn").forEach(b =>
        b.classList.toggle("active", b.dataset.path === path));
      activeMediaEl.textContent = path ? " · " + path.split("/").pop() : "";
    }}

    function setModeActive(modeId) {{
      activeEl.textContent = modeId;
      document.querySelectorAll(".mode-btn").forEach(b =>
        b.classList.toggle("active", b.dataset.mode === modeId));
      const firePanel = document.getElementById("fire-panel");
      const starPanel = document.getElementById("starfield-panel");
      const isFire = modeId === "flame" || modeId === "lava";
      const isStar = modeId === "starfield";
      const rainPanel = document.getElementById("rain-panel");
      const isRain = modeId === "matrix_rain";
      if (firePanel) firePanel.style.display = isFire ? "" : "none";
      if (starPanel) starPanel.style.display = isStar ? "" : "none";
      if (rainPanel) rainPanel.style.display = isRain ? "" : "none";
      if (isRain) loadRainConfig();
      const isEffect = EFFECT_MODES.includes(modeId);
      document.getElementById("effect-panel").style.display = isEffect ? "" : "none";
      if (isEffect) loadEffectConfig(modeId);
      if (isFire) {{
        currentFireMode = modeId;
        const title = document.getElementById("fire-panel-title");
        const hint = document.getElementById("fire-panel-hint");
        if (title) title.textContent = modeId === "lava" ? "Lava colors" : "Flame colors";
        if (hint) hint.textContent = modeId === "lava"
          ? "Dense heat field (~70% brightness). Night = 1.5 panels @ 10%."
          : "Sparse fire. Night = 1.5 panels @ 10%.";
        loadFireConfig(modeId);
      }}
      if (isStar) loadStarfieldConfig();
    }}

    document.querySelectorAll(".mode-btn").forEach(btn => {{
      btn.addEventListener("click", async () => {{
        const mode = btn.dataset.mode;
        const res = await fetch(`/api/mode/${{mode}}`, {{ method: "PUT" }});
        if (!res.ok) {{ showToast("Failed to switch mode"); return; }}
        const data = await res.json();
        setModeActive(data.active_mode);
        if (data.media_path) updateMediaHighlight(data.media_path);
        showToast(`Switched to ${{data.active_mode}}`);
      }});
    }});

    async function loadMedia() {{
      const list = document.getElementById("media-list");
      try {{
        const res = await fetch("/api/media");
        if (!res.ok) {{
          list.innerHTML = "<em>Could not load media list</em>";
          return;
        }}
        const files = await res.json();
        if (!files.length) {{
          list.innerHTML = "<em>No files in ~/matrix-gif-animations or ~/matrix-mp4-animations</em>";
          return;
        }}
        list.innerHTML = files.map(f => `
          <button class="media-btn${{f.path === currentMediaPath ? " active" : ""}}"
                  data-path="${{f.path.replace(/"/g, "&quot;")}}" type="button">
            <strong>${{f.name}}</strong><span>${{f.kind}} · ${{f.folder}}</span>
          </button>`).join("");
        list.querySelectorAll(".media-btn").forEach(btn => {{
          btn.addEventListener("click", async () => {{
            const res = await fetch("/api/media", {{
              method: "PUT",
              headers: {{ "Content-Type": "application/json" }},
              body: JSON.stringify({{ path: btn.dataset.path }}),
            }});
            if (!res.ok) {{ showToast("Failed to start media"); return; }}
            const data = await res.json();
            setModeActive(data.active_mode);
            updateMediaHighlight(data.media_path);
            showToast("Playing " + btn.dataset.path.split("/").pop());
          }});
        }});
      }} catch (err) {{
        list.innerHTML = "<em>Could not load media list</em>";
        console.error(err);
      }}
    }}

    if (currentMediaPath) updateMediaHighlight(currentMediaPath);
    loadMedia();

    const mqttMaster = document.getElementById("mqtt-master");
    const mqttSourcesEl = document.getElementById("mqtt-sources");
    let mqttState = null;

    async function saveMqtt(patch) {{
      const res = await fetch("/api/mqtt", {{
        method: "PUT",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify(patch),
      }});
      if (!res.ok) {{ showToast("Failed to update MQTT settings"); return null; }}
      mqttState = await res.json();
      renderMqtt(mqttState);
      showToast("MQTT settings updated");
      return mqttState;
    }}

    function renderMqtt(data) {{
      mqttMaster.checked = data.overlay_enabled;
      if (!data.sources.length) {{
        mqttSourcesEl.innerHTML = "<em>No MQTT sources configured for this display.</em>";
        return;
      }}
      mqttSourcesEl.innerHTML = data.sources.map(s => `
        <div class="mqtt-row">
          <label class="source-check">
            <input type="checkbox" data-source="${{s.id}}" ${{s.enabled ? "checked" : ""}} />
            <span>
              <strong>${{s.label}}</strong>
              <span class="source-topics">${{s.topics.join(", ")}}</span>
            </span>
          </label>
        </div>`).join("");
      mqttSourcesEl.querySelectorAll("input[data-source]").forEach(box => {{
        box.addEventListener("change", async () => {{
          const sources = {{}};
          sources[box.dataset.source] = box.checked;
          await saveMqtt({{ sources }});
        }});
      }});
    }}

    mqttMaster.addEventListener("change", async () => {{
      await saveMqtt({{ overlay_enabled: mqttMaster.checked }});
    }});

    async function loadMqtt() {{
      try {{
        const res = await fetch("/api/mqtt");
        if (!res.ok) {{
          mqttSourcesEl.innerHTML = "<em>Could not load MQTT settings</em>";
          return;
        }}
        mqttState = await res.json();
        renderMqtt(mqttState);
      }} catch (err) {{
        mqttSourcesEl.innerHTML = "<em>Could not load MQTT settings</em>";
        console.error(err);
      }}
    }}

    loadMqtt();

    const fireSwatches = document.getElementById("fire-swatches");
    const fireIntensity = document.getElementById("fire-intensity");
    const fireRotate = document.getElementById("fire-rotate");
    const fireStops = document.getElementById("fire-stops");
    let fireBusy = false;
    let currentFireMode = "flame";

    const INTENSITY_LABELS = ["Night (dim)", "1 panel", "2 panels", "Full (3)"];
    const ROTATE_LABELS = ["Off", "Slow", "Medium", "Fast"];

    function renderFireAll(cfg) {{
      renderFireSwatches(cfg);
      renderFireIntensity(cfg);
      renderFireRotate(cfg);
      renderFireStops(cfg);
    }}

    function renderFireRotate(data) {{
      if (!fireRotate) return;
      const labels = data.color_rotate_labels || ROTATE_LABELS;
      const active = data.color_rotate_speed ?? 0;
      fireRotate.innerHTML = `<span class="hint" style="flex:1 1 100%;margin:0 0 0.2rem">Color cycle</span>` +
        labels.map((label, idx) =>
          `<button type="button" class="${{idx === active ? "active" : ""}}" data-rotate-speed="${{idx}}">${{label}}</button>`
        ).join("");
      fireRotate.querySelectorAll("button[data-rotate-speed]").forEach(btn => {{
        btn.addEventListener("click", async () => {{
          if (fireBusy) return;
          fireBusy = true;
          try {{
            const res = await fetch(`/api/mode/${{currentFireMode}}/config`, {{
              method: "PUT",
              headers: {{ "Content-Type": "application/json" }},
              body: JSON.stringify({{ color_rotate_speed: Number(btn.dataset.rotateSpeed) }}),
            }});
            if (!res.ok) throw new Error("update failed");
            const cfg = await res.json();
            renderFireAll(cfg);
            showToast(`${{currentFireMode}} color cycle · ${{labels[cfg.color_rotate_speed ?? 0]}}`);
          }} catch (e) {{
            showToast("Failed to set color cycle");
          }} finally {{
            fireBusy = false;
          }}
        }});
      }});
    }}

    function renderFireIntensity(data) {{
      if (!fireIntensity) return;
      const active = data.intensity ?? 0;
      const gain = data.output_gain != null ? ` · ${{Math.round(data.output_gain * 100)}}%` : "";
      fireIntensity.innerHTML = INTENSITY_LABELS.map((label, idx) =>
        `<button type="button" class="${{idx === active ? "active" : ""}}" data-intensity="${{idx}}">${{label}}</button>`
      ).join("") + `<span class="hint" style="flex:1 1 100%;margin:0.25rem 0 0">Height ${{data.height_px || "—"}}px${{gain}}</span>`;
      fireIntensity.querySelectorAll("button[data-intensity]").forEach(btn => {{
        btn.addEventListener("click", async () => {{
          if (fireBusy) return;
          fireBusy = true;
          try {{
            const res = await fetch(`/api/mode/${{currentFireMode}}/config`, {{
              method: "PUT",
              headers: {{ "Content-Type": "application/json" }},
              body: JSON.stringify({{ intensity: Number(btn.dataset.intensity) }}),
            }});
            if (!res.ok) throw new Error("update failed");
            const cfg = await res.json();
            renderFireAll(cfg);
            showToast(`${{currentFireMode}} · ${{INTENSITY_LABELS[cfg.intensity ?? 0]}}`);
          }} catch (e) {{
            showToast("Failed to set intensity");
          }} finally {{
            fireBusy = false;
          }}
        }});
      }});
    }}

    function rgbToHex([r, g, b]) {{
      return "#" + [r, g, b].map(v => v.toString(16).padStart(2, "0")).join("");
    }}

    function renderFireStops(data) {{
      if (!fireStops) return;
      const stops = [
        ["core", "Core (hot)"],
        ["mid", "Mid"],
        ["tip", "Tip (bright)"],
      ];
      fireStops.innerHTML = stops.map(([key, label]) => `
        <label class="flame-stop">
          <span>${{label}}</span>
          <input type="color" data-fire-stop="${{key}}" value="${{rgbToHex(data[key])}}">
        </label>`).join("");
      fireStops.querySelectorAll("input[data-fire-stop]").forEach(inp => {{
        inp.addEventListener("change", async () => {{
          if (fireBusy) return;
          fireBusy = true;
          const hex = inp.value;
          const rgb = [parseInt(hex.slice(1,3),16), parseInt(hex.slice(3,5),16), parseInt(hex.slice(5,7),16)];
          try {{
            const body = {{}};
            body[inp.dataset.fireStop] = rgb;
            const res = await fetch(`/api/mode/${{currentFireMode}}/config`, {{
              method: "PUT",
              headers: {{ "Content-Type": "application/json" }},
              body: JSON.stringify(body),
            }});
            if (!res.ok) throw new Error("update failed");
            const cfg = await res.json();
            renderFireAll(cfg);
            showToast(`${{currentFireMode}} ${{inp.dataset.fireStop}} updated`);
          }} catch (e) {{
            showToast("Failed to set color");
          }} finally {{
            fireBusy = false;
          }}
        }});
      }});
    }}

    function renderFireSwatches(data) {{
      if (!fireSwatches) return;
      const activePreset = data.preset || null;
      fireSwatches.innerHTML = (data.presets || []).map(name => {{
        const rgb = {{
          orange: "#ff5a00", red: "#ff2800", yellow: "#ffc800",
          blue: "#2878ff", green: "#28ff50", purple: "#b428ff",
          cyan: "#00dcff", magenta: "#ff00b4", white: "#ffffff",
        }}[name] || "#ff5a00";
        const active = name === activePreset ? " active" : "";
        return `<button type="button" class="flame-swatch${{active}}" data-preset="${{name}}"
                style="background:${{rgb}}" title="${{name}}"><span>${{name}}</span></button>`;
      }}).join("");
      fireSwatches.querySelectorAll(".flame-swatch").forEach(btn => {{
        btn.addEventListener("click", async () => {{
          if (fireBusy) return;
          fireBusy = true;
          try {{
            const res = await fetch(`/api/mode/${{currentFireMode}}/config`, {{
              method: "PUT",
              headers: {{ "Content-Type": "application/json" }},
              body: JSON.stringify({{ preset: btn.dataset.preset }}),
            }});
            if (!res.ok) throw new Error("update failed");
            const cfg = await res.json();
            renderFireAll(cfg);
            showToast(`${{currentFireMode}} theme: ${{btn.dataset.preset}}`);
          }} catch (e) {{
            showToast("Failed to set theme");
          }} finally {{
            fireBusy = false;
          }}
        }});
      }});
    }}

    async function loadFireConfig(modeId) {{
      currentFireMode = modeId || currentFireMode;
      try {{
        const res = await fetch(`/api/mode/${{currentFireMode}}/config`);
        if (!res.ok) return;
        renderFireAll(await res.json());
      }} catch (e) {{
        console.error(e);
      }}
    }}

    const starIntensity = document.getElementById("star-intensity");
    const starColorModes = document.getElementById("star-color-modes");
    const starRotate = document.getElementById("star-rotate");
    const starSwatches = document.getElementById("star-swatches");
    const starStops = document.getElementById("star-stops");
    let starBusy = false;
    const STAR_INTENSITY_LABELS = ["Night (dim)", "Cruise", "Fast", "Warp"];
    const STAR_PRESET_RGB = {{
      classic: "#c8d2ff", warm: "#ffb450", cool: "#50a0ff",
      neon: "#ff50ff", ember: "#ff6414", aurora: "#50dc80",
    }};

    function renderStarRotate(data) {{
      if (!starRotate) return;
      const labels = data.color_rotate_labels || ROTATE_LABELS;
      const active = data.color_rotate_speed ?? 0;
      starRotate.innerHTML = `<span class="hint" style="flex:1 1 100%;margin:0 0 0.2rem">Color cycle</span>` +
        labels.map((label, idx) =>
          `<button type="button" class="${{idx === active ? "active" : ""}}" data-rotate-speed="${{idx}}">${{label}}</button>`
        ).join("");
      starRotate.querySelectorAll("button[data-rotate-speed]").forEach(btn => {{
        btn.addEventListener("click", async () => {{
          if (starBusy) return;
          starBusy = true;
          try {{
            const res = await fetch("/api/mode/starfield/config", {{
              method: "PUT",
              headers: {{ "Content-Type": "application/json" }},
              body: JSON.stringify({{ color_rotate_speed: Number(btn.dataset.rotateSpeed) }}),
            }});
            if (!res.ok) throw new Error("update failed");
            renderStarfieldAll(await res.json());
            showToast("Starfield color cycle · " + labels[Number(btn.dataset.rotateSpeed)]);
          }} catch (e) {{
            showToast("Failed to set color cycle");
          }} finally {{
            starBusy = false;
          }}
        }});
      }});
    }}

    function renderStarIntensity(data) {{
      if (!starIntensity) return;
      const active = data.intensity ?? 0;
      const meta = `${{data.star_count || "—"}} stars · ${{data.speed || "—"}}x · ${{Math.round((data.output_gain || 0) * 100)}}%`;
      starIntensity.innerHTML = STAR_INTENSITY_LABELS.map((label, idx) =>
        `<button type="button" class="${{idx === active ? "active" : ""}}" data-intensity="${{idx}}">${{label}}</button>`
      ).join("") + `<span class="hint" style="flex:1 1 100%;margin:0.25rem 0 0">${{meta}}</span>`;
      starIntensity.querySelectorAll("button[data-intensity]").forEach(btn => {{
        btn.addEventListener("click", async () => {{
          if (starBusy) return;
          starBusy = true;
          try {{
            const res = await fetch("/api/mode/starfield/config", {{
              method: "PUT",
              headers: {{ "Content-Type": "application/json" }},
              body: JSON.stringify({{ intensity: Number(btn.dataset.intensity) }}),
            }});
            if (!res.ok) throw new Error("update failed");
            renderStarfieldAll(await res.json());
            showToast("Starfield · " + STAR_INTENSITY_LABELS[Number(btn.dataset.intensity)]);
          }} catch (e) {{
            showToast("Failed to set starfield intensity");
          }} finally {{
            starBusy = false;
          }}
        }});
      }});
    }}

    function renderStarColorModes(data) {{
      if (!starColorModes) return;
      const active = data.color_mode || "depth";
      const modes = data.color_modes || ["white","warm","cool","rainbow","depth","dual"];
      starColorModes.innerHTML = modes.map(name =>
        `<button type="button" class="${{name === active ? "active" : ""}}" data-color-mode="${{name}}">${{name}}</button>`
      ).join("");
      starColorModes.querySelectorAll("button[data-color-mode]").forEach(btn => {{
        btn.addEventListener("click", async () => {{
          if (starBusy) return;
          starBusy = true;
          try {{
            const res = await fetch("/api/mode/starfield/config", {{
              method: "PUT",
              headers: {{ "Content-Type": "application/json" }},
              body: JSON.stringify({{ color_mode: btn.dataset.colorMode }}),
            }});
            if (!res.ok) throw new Error("update failed");
            renderStarfieldAll(await res.json());
            showToast("Color mode · " + btn.dataset.colorMode);
          }} catch (e) {{
            showToast("Failed to set color mode");
          }} finally {{
            starBusy = false;
          }}
        }});
      }});
    }}

    function renderStarSwatches(data) {{
      if (!starSwatches) return;
      const activePreset = data.preset || null;
      starSwatches.innerHTML = (data.presets || []).map(name => {{
        const rgb = STAR_PRESET_RGB[name] || "#ffffff";
        const active = name === activePreset ? " active" : "";
        return `<button type="button" class="flame-swatch${{active}}" data-preset="${{name}}"
                style="background:${{rgb}}" title="${{name}}"><span>${{name}}</span></button>`;
      }}).join("");
      starSwatches.querySelectorAll(".flame-swatch").forEach(btn => {{
        btn.addEventListener("click", async () => {{
          if (starBusy) return;
          starBusy = true;
          try {{
            const res = await fetch("/api/mode/starfield/config", {{
              method: "PUT",
              headers: {{ "Content-Type": "application/json" }},
              body: JSON.stringify({{ preset: btn.dataset.preset }}),
            }});
            if (!res.ok) throw new Error("update failed");
            renderStarfieldAll(await res.json());
            showToast("Starfield theme · " + btn.dataset.preset);
          }} catch (e) {{
            showToast("Failed to set theme");
          }} finally {{
            starBusy = false;
          }}
        }});
      }});
    }}

    function renderStarStops(data) {{
      if (!starStops) return;
      const stops = [
        ["near", "Near (bright)"],
        ["mid", "Mid"],
        ["far", "Far (dim)"],
      ];
      starStops.innerHTML = stops.map(([key, label]) => `
        <label class="flame-stop">
          <span>${{label}}</span>
          <input type="color" data-star-stop="${{key}}" value="${{rgbToHex(data[key])}}">
        </label>`).join("");
      starStops.querySelectorAll("input[data-star-stop]").forEach(inp => {{
        inp.addEventListener("change", async () => {{
          if (starBusy) return;
          starBusy = true;
          const hex = inp.value;
          const rgb = [parseInt(hex.slice(1,3),16), parseInt(hex.slice(3,5),16), parseInt(hex.slice(5,7),16)];
          try {{
            const body = {{}};
            body[inp.dataset.starStop] = rgb;
            const res = await fetch("/api/mode/starfield/config", {{
              method: "PUT",
              headers: {{ "Content-Type": "application/json" }},
              body: JSON.stringify(body),
            }});
            if (!res.ok) throw new Error("update failed");
            renderStarfieldAll(await res.json());
            showToast("Starfield " + inp.dataset.starStop + " updated");
          }} catch (e) {{
            showToast("Failed to set star color");
          }} finally {{
            starBusy = false;
          }}
        }});
      }});
    }}

    function renderStarfieldAll(cfg) {{
      renderStarIntensity(cfg);
      renderStarColorModes(cfg);
      renderStarRotate(cfg);
      renderStarSwatches(cfg);
      renderStarStops(cfg);
    }}

    async function loadStarfieldConfig() {{
      try {{
        const res = await fetch("/api/mode/starfield/config");
        if (!res.ok) return;
        renderStarfieldAll(await res.json());
      }} catch (e) {{
        console.error(e);
      }}
    }}

    let rainBusy = false;

    async function saveRain(patch, label) {{
      if (rainBusy) return;
      rainBusy = true;
      try {{
        const res = await fetch("/api/mode/matrix_rain/config", {{
          method: "PUT",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify(patch),
        }});
        if (!res.ok) throw new Error("update failed");
        renderRain(await res.json());
        showToast("Matrix rain · " + label);
      }} catch (e) {{
        showToast("Failed to update matrix rain");
      }} finally {{
        rainBusy = false;
      }}
    }}

    function renderRain(cfg) {{
      const speedEl = document.getElementById("rain-speed");
      speedEl.innerHTML = cfg.speed_labels.map((label, i) =>
        `<button type="button" class="${{i === cfg.speed ? "active" : ""}}" data-speed="${{i}}">${{label}}</button>`
      ).join("");
      speedEl.querySelectorAll("button[data-speed]").forEach(btn =>
        btn.addEventListener("click", () =>
          saveRain({{ speed: Number(btn.dataset.speed) }}, btn.textContent)));

      const swatches = document.getElementById("rain-swatches");
      swatches.innerHTML = Object.entries(cfg.presets).map(([name, rgb]) => {{
        const active = name === cfg.preset ? " active" : "";
        return `<button type="button" class="flame-swatch${{active}}" data-preset="${{name}}"
                style="background:${{rgbToHex(rgb)}}" title="${{name}}"><span>${{name}}</span></button>`;
      }}).join("");
      swatches.querySelectorAll(".flame-swatch").forEach(btn =>
        btn.addEventListener("click", () =>
          saveRain({{ preset: btn.dataset.preset }}, btn.dataset.preset)));

      document.getElementById("rain-color").value = rgbToHex(cfg.color);
    }}

    document.getElementById("rain-color").addEventListener("change", e => {{
      const hex = e.target.value;
      const rgb = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16));
      saveRain({{ color: rgb }}, hex);
    }});

    async function loadRainConfig() {{
      try {{
        const res = await fetch("/api/mode/matrix_rain/config");
        if (res.ok) renderRain(await res.json());
      }} catch (e) {{
        console.error(e);
      }}
    }}

{EFFECT_JS}
    const EFFECT_MODES = {json.dumps(list(EFFECT_MODE_IDS))};
    let effectBusy = false;

    function renderEffect(modeId, cfg) {{
      document.getElementById("effect-title").textContent = cfg.title;
      document.getElementById("effect-hint").textContent = cfg.hint + " This display only.";
      renderEffectPanel(document.getElementById("effect-controls"), cfg,
        (patch, label) => saveEffect(modeId, patch, label));
    }}

    async function saveEffect(modeId, patch, label) {{
      if (effectBusy) return;
      effectBusy = true;
      try {{
        const res = await fetch(`/api/mode/${{modeId}}/effect`, {{
          method: "PUT",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify(patch),
        }});
        const data = await res.json().catch(() => ({{}}));
        if (!res.ok) throw new Error(data.detail || "update failed");
        renderEffect(modeId, data);
        showToast(`${{data.title}} · ${{label}}`);
      }} catch (e) {{
        showToast(String(e.message || e));
      }} finally {{
        effectBusy = false;
      }}
    }}

    async function loadEffectConfig(modeId) {{
      try {{
        const res = await fetch(`/api/mode/${{modeId}}/effect`);
        if (res.ok) renderEffect(modeId, await res.json());
      }} catch (e) {{
        console.error(e);
      }}
    }}

    setModeActive({json.dumps(state.active_mode)});
  </script>
</body>
</html>"""


@app.get("/api/modes", response_model=List[ModeSummary])
def api_list_modes() -> List[ModeSummary]:
    return [
        ModeSummary(id=m.id, label=m.label, description=m.description)
        for m in list_modes()
    ]


@app.get("/api/media", response_model=List[MediaFileSummary])
def api_list_media() -> List[MediaFileSummary]:
    return [
        MediaFileSummary(path=f.path, name=f.name, kind=f.kind, folder=f.folder)
        for f in list_media_files()
    ]


@app.put("/api/media", response_model=StateResponse)
def api_select_media(body: MediaSelectRequest) -> StateResponse:
    known = {f.path for f in list_media_files()}
    if body.path not in known:
        # rescan once in case a new file was added
        known = {f.path for f in list_media_files(refresh=True)}
    if body.path not in known:
        raise HTTPException(status_code=404, detail=f"Unknown media file: {body.path}")
    state = set_media_path(body.path)
    return _state_response(state)


@app.get("/api/state", response_model=StateResponse)
def api_get_state() -> StateResponse:
    return _state_response(load_state())


@app.put("/api/mode/{mode_id}", response_model=StateResponse)
def api_set_mode(mode_id: str) -> StateResponse:
    if mode_id not in MODES:
        raise HTTPException(status_code=404, detail=f"Unknown mode: {mode_id}")
    state = set_active_mode(mode_id)
    return _state_response(state)


def _validate_rgb_field(name: str, value: Optional[List[int]]) -> None:
    if value is None:
        return
    if len(value) != 3:
        raise HTTPException(status_code=400, detail=f"{name} must be [r, g, b]")
    if any(c < 0 or c > 255 for c in value):
        raise HTTPException(status_code=400, detail=f"{name} values must be 0–255")


@app.get("/api/mode/starfield/config", response_model=StarfieldConfigResponse)
def api_get_starfield_config() -> StarfieldConfigResponse:
    return _starfield_config_response()


@app.put("/api/mode/starfield/config", response_model=StarfieldConfigResponse)
def api_set_starfield_config(body: StarfieldConfigRequest) -> StarfieldConfigResponse:
    if body.preset is not None and body.preset not in STARFIELD_PRESETS:
        raise HTTPException(status_code=400, detail=f"Unknown preset: {body.preset}")
    if body.color_mode is not None and body.color_mode not in COLOR_MODES:
        raise HTTPException(status_code=400, detail=f"Unknown color_mode: {body.color_mode}")
    if body.intensity is not None and not 0 <= body.intensity <= 3:
        raise HTTPException(status_code=400, detail="intensity must be 0–3")
    if body.color_rotate_speed is not None and not 0 <= body.color_rotate_speed <= 3:
        raise HTTPException(status_code=400, detail="color_rotate_speed must be 0–3")
    for field in ("near", "mid", "far"):
        _validate_rgb_field(field, getattr(body, field))
    if all(
        getattr(body, k) is None
        for k in (
            "preset",
            "color_mode",
            "intensity",
            "near",
            "mid",
            "far",
            "color_rotate_speed",
        )
    ):
        raise HTTPException(
            status_code=400,
            detail="Provide preset, color_mode, intensity, color_rotate_speed, and/or color stops",
        )
    set_mode_config("starfield", body.model_dump(exclude_none=True))
    return _starfield_config_response()


def _starfield_config_response() -> StarfieldConfigResponse:
    state = load_state()
    cfg = (state.mode_config or {}).get("starfield") if state.mode_config else None
    cfg_dict = cfg if isinstance(cfg, dict) else {}
    return StarfieldConfigResponse(**starfield_config_for_api(cfg_dict))


@app.get("/api/mode/matrix_rain/config", response_model=MatrixRainConfigResponse)
def api_get_matrix_rain_config() -> MatrixRainConfigResponse:
    return _matrix_rain_config_response()


@app.put("/api/mode/matrix_rain/config", response_model=MatrixRainConfigResponse)
def api_set_matrix_rain_config(body: MatrixRainConfigRequest) -> MatrixRainConfigResponse:
    if body.preset is not None and body.preset not in RAIN_PRESETS:
        raise HTTPException(status_code=400, detail=f"Unknown preset: {body.preset}")
    if body.speed is not None and not 0 <= body.speed <= RAIN_MAX_SPEED:
        raise HTTPException(status_code=400, detail=f"speed must be 0–{RAIN_MAX_SPEED}")
    _validate_rgb_field("color", body.color)
    if body.preset is None and body.color is None and body.speed is None:
        raise HTTPException(status_code=400, detail="Provide preset, color, and/or speed")
    set_mode_config("matrix_rain", body.model_dump(exclude_none=True))
    return _matrix_rain_config_response()


def _matrix_rain_config_response() -> MatrixRainConfigResponse:
    state = load_state()
    cfg = (state.mode_config or {}).get("matrix_rain") if state.mode_config else None
    return MatrixRainConfigResponse(**matrix_rain_config_for_api(cfg if isinstance(cfg, dict) else {}))


def _effect_response(mode_id: str) -> dict:
    if mode_id not in EFFECT_MODE_IDS:
        raise HTTPException(status_code=404, detail=f"{mode_id} has no effect settings")
    state = load_state()
    cfg = (state.mode_config or {}).get(mode_id)
    return effect_config_for_api(mode_id, cfg if isinstance(cfg, dict) else None)


@app.get("/api/mode/{mode_id}/effect")
def api_get_effect_config(mode_id: str) -> dict:
    return _effect_response(mode_id)


@app.put("/api/mode/{mode_id}/effect")
def api_set_effect_config(mode_id: str, body: dict = Body(...)) -> dict:
    if mode_id not in EFFECT_MODE_IDS:
        raise HTTPException(status_code=404, detail=f"{mode_id} has no effect settings")
    try:
        patch = validate_effect_patch(mode_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    set_mode_config(mode_id, patch)
    return _effect_response(mode_id)


@app.get("/api/mode/{mode_id}/config", response_model=FireConfigResponse)
def api_get_fire_config(mode_id: str) -> FireConfigResponse:
    if mode_id not in ("flame", "lava"):
        raise HTTPException(status_code=404, detail="Unknown fire mode config")
    return _fire_config_response(mode_id)


@app.put("/api/mode/{mode_id}/config", response_model=FireConfigResponse)
def api_set_fire_config(mode_id: str, body: FireConfigRequest) -> FireConfigResponse:
    if mode_id not in ("flame", "lava"):
        raise HTTPException(status_code=404, detail="Unknown fire mode config")
    if body.preset is not None and body.preset not in FLAME_PRESETS:
        raise HTTPException(status_code=400, detail=f"Unknown preset: {body.preset}")
    if body.intensity is not None and not 0 <= body.intensity <= 3:
        raise HTTPException(status_code=400, detail="intensity must be 0–3")
    if body.color_rotate_speed is not None and not 0 <= body.color_rotate_speed <= 3:
        raise HTTPException(status_code=400, detail="color_rotate_speed must be 0–3")
    for field in ("core", "mid", "tip", "ember"):
        _validate_rgb_field(field, getattr(body, field))
    if all(
        getattr(body, k) is None
        for k in (
            "preset",
            "intensity",
            "core",
            "mid",
            "tip",
            "ember",
            "color_rotate_speed",
        )
    ):
        raise HTTPException(
            status_code=400,
            detail="Provide preset, intensity, color_rotate_speed, and/or color stops",
        )
    patch = body.model_dump(exclude_none=True)
    set_mode_config(mode_id, patch)
    return _fire_config_response(mode_id)


def _fire_config_response(mode_id: str) -> FireConfigResponse:
    state = load_state()
    cfg = (state.mode_config or {}).get(mode_id) if state.mode_config else None
    cfg_dict = cfg if isinstance(cfg, dict) else {}
    data = flame_config_for_api(cfg_dict) if mode_id == "flame" else lava_config_for_api(cfg_dict)
    return FireConfigResponse(**data)


@app.get("/api/mqtt", response_model=MqttOverlayResponse)
def api_get_mqtt() -> MqttOverlayResponse:
    return _mqtt_overlay_response()


@app.put("/api/mqtt", response_model=MqttOverlayResponse)
def api_update_mqtt(body: MqttOverlayUpdateRequest) -> MqttOverlayResponse:
    topics = _mqtt_subscribed_topics()
    wall_ids = set(wall_source_ids(topics))
    if body.sources:
        unknown = [k for k in body.sources if k not in wall_ids]
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown or unavailable sources for this display: {', '.join(unknown)}",
            )
    update_overlay_settings(
        overlay_enabled=body.overlay_enabled,
        sources=body.sources,
        subscribed_topics=topics,
    )
    return _mqtt_overlay_response()


@app.post("/api/mqtt/purge")
def api_purge_mqtt() -> dict:
    """Drop the caption on screen and anything that arrived before now."""
    return {"purged_at": request_mqtt_purge()}


def _showing_summary(showing) -> Optional[dict]:
    if showing is None:
        return None
    return {
        "id": showing.message["id"],
        "name": showing.message["name"],
        "start": showing.start.isoformat(),
        "end": showing.end.isoformat(),
    }


def _messages_response() -> dict:
    stored = load_message_state()
    tz = BrightnessSchedule.load_from_config().timezone
    now = datetime.now(tz)
    preview = load_preview()
    return {
        **stored,
        "timezone": tz.key,
        "now_showing": _showing_summary(current_showing(stored["messages"], now)),
        "next_showing": _showing_summary(next_showing(stored["messages"], now)),
        "preview": (
            {"id": preview["message"]["id"], "until": preview["until"]} if preview else None
        ),
    }


@app.get("/api/messages")
def api_get_messages() -> dict:
    return _messages_response()


@app.put("/api/messages")
def api_put_messages(body: dict = Body(...)) -> dict:
    try:
        save_messages(body.get("messages"))
    except MessageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _messages_response()


@app.post("/api/messages/preview")
def api_preview_message(body: dict = Body(...)) -> dict:
    """Show a message now. Send ``{"id": ...}`` for a stored one or ``{"message": {...}}``."""
    message = body.get("message")
    if message is None:
        stored = {m["id"]: m for m in load_message_state()["messages"]}
        message = stored.get(str(body.get("id", "")))
        if message is None:
            raise HTTPException(status_code=404, detail="No stored message with that id")
    seconds = body.get("seconds")
    if seconds is not None and (not isinstance(seconds, int) or not 1 <= seconds <= 300):
        raise HTTPException(status_code=400, detail="seconds must be an integer 1-300")
    try:
        set_preview(message, seconds)
    except MessageError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _messages_response()


@app.delete("/api/messages/preview")
def api_clear_preview() -> dict:
    clear_preview()
    return _messages_response()


def _state_response(state) -> StateResponse:
    return StateResponse(
        active_mode=state.active_mode,
        media_path=state.media_path,
        mode_config=state.mode_config,
        updated_at=state.updated_at,
        modes=[ModeSummary(id=m.id, label=m.label, description=m.description) for m in list_modes()],
    )
