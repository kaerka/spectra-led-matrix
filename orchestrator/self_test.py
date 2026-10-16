"""Full-system self-test: matrix wall demos + Pi5 hardware validation."""

from __future__ import annotations

import json
import socket
import subprocess
import threading
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import paho.mqtt.client as mqtt

from orchestrator.clients import MatrixHostClient
from orchestrator.config import MatrixHostConfig, MqttConfig, OrchestratorConfig

MATRIX_DEMO_MODES: List[Tuple[str, str]] = [
    ("game_of_life", "GAME OF LIFE"),
    ("world_clock", "WORLD CLOCK"),
    ("weather", "WEATHER + CALENDAR"),
]

HOST_COLORS: Dict[str, List[int]] = {
    "upper": [255, 140, 0],
    "lower": [80, 200, 255],
}

USB_DEVICES: Dict[str, Tuple[str, str, str]] = {
    "respeaker": ("2886", "0018", "ReSpeaker 4-mic"),
    "coral": ("1a6e", "089a", "Coral USB TPU"),
    "mesh_toad": ("1a86", "5512", "MeshToad CH341"),
    "usb_wifi": ("0e8d", "7612", "MediaTek USB WiFi"),
}


@dataclass
class TestStep:
    id: str
    name: str
    category: str
    status: str = "pending"
    message: str = ""
    duration_ms: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "status": self.status,
            "message": self.message,
            "duration_ms": round(self.duration_ms, 1),
        }


@dataclass
class SelfTestRun:
    running: bool = False
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    dwell_seconds: float = 6.0
    steps: List[TestStep] = field(default_factory=list)
    error: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        passed = sum(1 for s in self.steps if s.status == "pass")
        failed = sum(1 for s in self.steps if s.status == "fail")
        warned = sum(1 for s in self.steps if s.status == "warn")
        total = len(self.steps)
        done = sum(1 for s in self.steps if s.status in ("pass", "fail", "warn"))
        current = next((s for s in self.steps if s.status == "running"), None)
        duration = 0.0
        if self.started_at:
            end = self.finished_at or time.time()
            duration = end - self.started_at
        return {
            "running": self.running,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "dwell_seconds": self.dwell_seconds,
            "progress": {"done": done, "total": total},
            "summary": {
                "passed": passed,
                "failed": failed,
                "warned": warned,
                "total": total,
                "ok": failed == 0,
                "duration_sec": round(duration, 1),
            },
            "current_step": current.as_dict() if current else None,
            "steps": [s.as_dict() for s in self.steps],
            "error": self.error,
        }


class SelfTestRunner:
    def __init__(self, cfg: OrchestratorConfig) -> None:
        self._cfg = cfg
        self._lock = threading.Lock()
        self._run = SelfTestRun()
        self._thread: Optional[threading.Thread] = None

    def status(self) -> dict[str, Any]:
        with self._lock:
            return self._run.as_dict()

    def start(self, dwell_seconds: float = 6.0) -> dict[str, Any]:
        dwell = max(3.0, min(15.0, float(dwell_seconds)))
        with self._lock:
            if self._run.running:
                raise RuntimeError("Self-test already running")
            self._run = SelfTestRun(running=True, started_at=time.time(), dwell_seconds=dwell)
            self._thread = threading.Thread(target=self._execute, args=(dwell,), daemon=True)
            self._thread.start()
            return self._run.as_dict()

    def _clients(self) -> List[MatrixHostClient]:
        return [
            MatrixHostClient(host, self._cfg.request_timeout_seconds)
            for host in self._cfg.matrix_hosts
        ]

    def _client(self, host_id: str) -> MatrixHostClient:
        for host in self._cfg.matrix_hosts:
            if host.id == host_id:
                return MatrixHostClient(host, self._cfg.request_timeout_seconds)
        raise KeyError(host_id)

    def _set_step(self, step: TestStep, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            setattr(step, key, value)

    def _run_step(
        self,
        step_id: str,
        name: str,
        category: str,
        fn: Callable[[], Tuple[str, str]],
    ) -> None:
        step = TestStep(id=step_id, name=name, category=category, status="running")
        with self._lock:
            self._run.steps.append(step)
        t0 = time.time()
        try:
            status, message = fn()
            self._set_step(
                step,
                status=status,
                message=message,
                duration_ms=(time.time() - t0) * 1000,
            )
        except Exception as exc:
            self._set_step(
                step,
                status="fail",
                message=str(exc),
                duration_ms=(time.time() - t0) * 1000,
            )

    def _sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    def _mqtt_overlay(
        self,
        text: str,
        *,
        color: Optional[List[int]] = None,
        ttl: Optional[int] = None,
    ) -> None:
        mqtt_cfg = self._cfg.mqtt
        payload = json.dumps(
            {
                "text": text,
                "ttl": ttl or int(self._run.dwell_seconds + 4),
                "color": color or [0, 255, 120],
            }
        )
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        client.connect(mqtt_cfg.broker, mqtt_cfg.port, 60)
        client.loop_start()
        try:
            info = client.publish(mqtt_cfg.test_topic, payload, qos=0)
            info.wait_for_publish(timeout=3.0)
        finally:
            client.loop_stop()
            client.disconnect()

    def _host_from_api(self, api_base: str) -> str:
        parsed = urllib.parse.urlparse(api_base)
        return parsed.hostname or ""

    def _ping(self, host: str) -> bool:
        if not host:
            return False
        result = subprocess.run(
            ["ping", "-c", "1", "-W", "2", host],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.returncode == 0

    def _systemctl_active(self, unit: str) -> bool:
        result = subprocess.run(
            ["systemctl", "is-active", unit],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout.strip() == "active"

    def _nmcli_connected(self, iface: str) -> bool:
        result = subprocess.run(
            ["nmcli", "-t", "-f", "DEVICE,STATE", "dev"],
            capture_output=True,
            text=True,
            check=False,
        )
        for line in result.stdout.splitlines():
            if ":" not in line:
                continue
            dev, state = line.split(":", 1)
            if dev == iface:
                return state == "connected"
        return False

    def _lsusb_has(self, vendor: str, product: str) -> bool:
        result = subprocess.run(["lsusb"], capture_output=True, text=True, check=False)
        needle = f"{vendor}:{product}".lower()
        return needle in result.stdout.lower()

    def _tcp_open(self, host: str, port: int, timeout: float = 2.0) -> bool:
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            return False

    def _gps_ok(self) -> Tuple[str, str]:
        if not self._systemctl_active("gpsd"):
            return "fail", "gpsd not active"
        result = subprocess.run(
            ["chronyc", "-n", "sources"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        for line in result.stdout.splitlines():
            if "GPS" in line:
                if line.strip().startswith("#?"):
                    return "warn", "GPS visible to chrony but no fix yet"
                if "^" in line[:2] or line.strip().startswith("#-"):
                    return "pass", "GPS refclock reachable in chrony"
        return "warn", "gpsd running; chrony GPS source not listed yet"

    def _build_plan(self) -> List[Tuple[str, str, str, Callable[[], Tuple[str, str]]]]:
        plan: List[Tuple[str, str, str, Callable[[], Tuple[str, str]]]] = []
        clients = self._clients()
        saved_modes: Dict[str, str] = {}

        def save_modes() -> Tuple[str, str]:
            for client in clients:
                state = client.get_state()
                if state.online and isinstance(state.data, dict):
                    saved_modes[client.cfg.id] = str(state.data.get("active_mode", "weather"))
            return "pass", f"Saved modes for {len(saved_modes)} wall(s)"

        def intro_step() -> Tuple[str, str]:
            try:
                self._mqtt_overlay("▶ SPECTRA SELF-TEST STARTING ◀", ttl=8)
                self._sleep(2.0)
                return "pass", "Intro banner on both walls"
            except Exception as exc:
                return "fail", str(exc)

        plan.append(("intro", "Self-test intro", "matrix", intro_step))

        plan.append(("matrix.save_state", "Save display modes", "matrix", save_modes))

        for client in clients:
            host = client.cfg
            color = HOST_COLORS.get(host.id, [0, 255, 120])
            label = host.label.upper()

            def make_reach(c: MatrixHostClient = client, h: MatrixHostConfig = host) -> Callable[[], Tuple[str, str]]:
                def _check() -> Tuple[str, str]:
                    result = c.get_state()
                    if result.online:
                        return "pass", f"{h.label} API reachable ({result.status_code})"
                    return "fail", result.error or "unreachable"
                return _check

            plan.append((f"matrix.{host.id}.reach", f"{label} — API", "matrix", make_reach()))

            for mode_id, mode_label in MATRIX_DEMO_MODES:
                def make_mode(
                    c: MatrixHostClient = client,
                    h: MatrixHostConfig = host,
                    mid: str = mode_id,
                    mlabel: str = mode_label,
                    col: List[int] = color,
                ) -> Callable[[], Tuple[str, str]]:
                    def _demo() -> Tuple[str, str]:
                        result = c.set_mode(mid)
                        if not result.online:
                            return "fail", result.error or f"mode {mid} failed"
                        self._mqtt_overlay(f"{h.label.upper()}\n{mlabel}", color=col)
                        self._sleep(self._run.dwell_seconds)
                        return "pass", f"{h.label} → {mid} ({self._run.dwell_seconds:.0f}s)"
                    return _demo

                plan.append(
                    (f"matrix.{host.id}.{mode_id}", f"{label} — {mode_label.title()}", "matrix", make_mode())
                )

        def sync_walls() -> Tuple[str, str]:
            ok = True
            errors: List[str] = []
            for client in clients:
                result = client.set_mode("game_of_life")
                if not result.online:
                    ok = False
                    errors.append(f"{client.cfg.id}: {result.error}")
            self._mqtt_overlay("◆ BOTH WALLS — SYNC ◆", color=[200, 100, 255], ttl=10)
            self._sleep(self._run.dwell_seconds)
            if ok:
                return "pass", "Both walls synced to game_of_life"
            return "fail", "; ".join(errors)

        plan.append(("matrix.sync", "Sync both walls", "matrix", sync_walls))

        def mqtt_both() -> Tuple[str, str]:
            self._mqtt_overlay("MQTT OVERLAY\nBOTH WALLS OK", color=[0, 255, 120], ttl=10)
            self._sleep(3.0)
            return "pass", "Dual-wall MQTT overlay published"

        plan.append(("matrix.mqtt_dual", "Dual-wall MQTT banner", "matrix", mqtt_both))

        def hw_banner() -> Tuple[str, str]:
            try:
                self._mqtt_overlay("VALIDATING\nPI5 HARDWARE…", color=[255, 255, 255], ttl=12)
                return "pass", "Hardware phase banner"
            except Exception as exc:
                return "fail", str(exc)

        plan.append(("hw.banner", "Hardware validation", "hardware", hw_banner))

        plan.append(("hw.eth0", "Ethernet (matrix link)", "network", lambda: (
            ("pass", "eth0 connected") if self._nmcli_connected("eth0")
            else ("fail", "eth0 not connected")
        )))

        plan.append(("hw.wlan1", "USB WiFi (home LAN)", "network", lambda: (
            ("pass", "wlan1 connected") if self._nmcli_connected("wlan1")
            else ("warn", "wlan1 not connected")
        )))

        for client in clients:
            ip = self._host_from_api(client.cfg.api_base)

            def make_ping(c: MatrixHostClient = client, addr: str = ip) -> Callable[[], Tuple[str, str]]:
                def _ping_host() -> Tuple[str, str]:
                    if self._ping(addr):
                        return "pass", f"ping {addr} OK"
                    return "fail", f"ping {addr} failed"
                return _ping_host

            plan.append((f"network.ping.{client.cfg.id}", f"Ping {client.cfg.label}", "network", make_ping()))

        def mqtt_check() -> Tuple[str, str]:
            if self._try_mqtt():
                return "pass", "publish OK"
            return "fail", "MQTT publish failed"

        plan.append(("hw.mqtt", "Mosquitto broker", "hardware", mqtt_check))

        plan.append(("hw.chrony", "Chrony time sync", "hardware", lambda: (
            "pass" if self._systemctl_active("chrony") else "fail",
            "chrony active" if self._systemctl_active("chrony") else "chrony inactive",
        )))

        plan.append(("hw.gps", "GPS / gpsd", "hardware", self._gps_ok))

        for key, (vendor, product, label) in USB_DEVICES.items():
            plan.append(
                (
                    f"hw.usb.{key}",
                    f"USB — {label}",
                    "hardware",
                    lambda v=vendor, p=product, n=label: (
                        ("pass", f"{n} detected") if self._lsusb_has(v, p) else ("fail", f"{n} not found"),
                    ),
                )
            )

        plan.append(("hw.whisper.capture", "Whisper capture", "hardware", lambda: (
            ("pass", "capture active") if self._systemctl_active("spectra-whisper-capture")
            else ("warn", "capture stopped"),
        )))

        plan.append(("hw.whisper.transcribe", "Whisper transcribe", "hardware", lambda: (
            ("pass", "transcribe active") if self._systemctl_active("spectra-whisper-transcribe")
            else ("warn", "transcribe stopped"),
        )))

        plan.append(("hw.meshtasticd", "Meshtastic daemon", "hardware", lambda: (
            "pass" if self._systemctl_active("meshtasticd") else "warn",
            "meshtasticd active" if self._systemctl_active("meshtasticd") else "meshtasticd inactive",
        )))

        plan.append(("hw.mesh.bridge", "Meshtastic MQTT bridge", "hardware", lambda: (
            "pass" if self._systemctl_active("spectra-meshtastic-bridge") else "warn",
            "bridge active" if self._systemctl_active("spectra-meshtastic-bridge") else "bridge inactive",
        )))

        plan.append(("hw.mesh.tcp", "Meshtastic TCP :4403", "hardware", lambda: (
            "pass" if self._tcp_open("127.0.0.1", 4403) else "warn",
            "port 4403 open" if self._tcp_open("127.0.0.1", 4403) else "port 4403 closed",
        )))

        def restore_modes() -> Tuple[str, str]:
            restored = 0
            for client in clients:
                mode = saved_modes.get(client.cfg.id)
                if mode:
                    if client.set_mode(mode).online:
                        restored += 1
            return "pass", f"Restored {restored} wall mode(s)"

        def finish() -> Tuple[str, str]:
            with self._lock:
                passed = sum(1 for s in self._run.steps if s.status == "pass")
                failed = sum(1 for s in self._run.steps if s.status == "fail")
                total = len(self._run.steps)
            msg = f"SELF-TEST COMPLETE\n{passed}/{total} PASSED"
            if failed:
                msg += f" · {failed} FAILED"
            self._mqtt_overlay(msg, color=[0, 255, 120] if failed == 0 else [255, 80, 80], ttl=15)
            return "pass" if failed == 0 else "warn", f"{passed} passed, {failed} failed"

        plan.append(("matrix.restore", "Restore display modes", "matrix", restore_modes))
        plan.append(("finish", "Self-test complete", "matrix", finish))

        return plan

    def _try_mqtt(self) -> bool:
        try:
            self._mqtt_overlay("MQTT OK", ttl=3, color=[0, 255, 120])
            return True
        except Exception:
            return False

    def _execute(self, dwell_seconds: float) -> None:
        try:
            with self._lock:
                self._run.dwell_seconds = dwell_seconds
            for step_id, name, category, fn in self._build_plan():
                self._run_step(step_id, name, category, fn)
        except Exception as exc:
            with self._lock:
                self._run.error = str(exc)
        finally:
            with self._lock:
                self._run.running = False
                self._run.finished_at = time.time()


_runner: Optional[SelfTestRunner] = None


def get_runner(cfg: OrchestratorConfig) -> SelfTestRunner:
    global _runner
    if _runner is None:
        _runner = SelfTestRunner(cfg)
    return _runner
