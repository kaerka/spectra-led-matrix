"""Wireframe 3D — spinning cube or torus projected with perspective."""

from __future__ import annotations

import numpy as np

from display.modes.effect_base import EffectField, EffectMode

_RPM = (8.0, 18.0, 32.0, 55.0)


def _line(buf: np.ndarray, x0: float, y0: float, x1: float, y1: float, color: np.ndarray) -> None:
    h, w = buf.shape[:2]
    steps = max(abs(int(round(x1 - x0))), abs(int(round(y1 - y0))), 1)
    for i in range(steps + 1):
        t = i / steps
        x = int(round(x0 + (x1 - x0) * t))
        y = int(round(y0 + (y1 - y0) * t))
        if 0 <= x < w and 0 <= y < h:
            buf[y, x] = color


def _rot_xyz(points: np.ndarray, ax: float, ay: float, az: float) -> np.ndarray:
    cx, sx = np.cos(ax), np.sin(ax)
    cy, sy = np.cos(ay), np.sin(ay)
    cz, sz = np.cos(az), np.sin(az)
    rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]], dtype=np.float32)
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]], dtype=np.float32)
    rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]], dtype=np.float32)
    return (points @ (rx @ ry @ rz).T).astype(np.float32)


def _cube_edges() -> tuple[np.ndarray, list[tuple[int, int]]]:
    v = np.array(
        [
            [-1, -1, -1],
            [1, -1, -1],
            [1, 1, -1],
            [-1, 1, -1],
            [-1, -1, 1],
            [1, -1, 1],
            [1, 1, 1],
            [-1, 1, 1],
        ],
        dtype=np.float32,
    )
    e = [
        (0, 1),
        (1, 2),
        (2, 3),
        (3, 0),
        (4, 5),
        (5, 6),
        (6, 7),
        (7, 4),
        (0, 4),
        (1, 5),
        (2, 6),
        (3, 7),
    ]
    return v, e


def _torus_mesh(n_u: int = 10, n_v: int = 8, R: float = 1.0, r: float = 0.38) -> tuple[np.ndarray, list[tuple[int, int]]]:
    u = np.linspace(0, 2 * np.pi, n_u, endpoint=False)
    v = np.linspace(0, 2 * np.pi, n_v, endpoint=False)
    pts = []
    for ui in u:
        for vi in v:
            x = (R + r * np.cos(vi)) * np.cos(ui)
            y = (R + r * np.cos(vi)) * np.sin(ui)
            z = r * np.sin(vi)
            pts.append((x, y, z))
    verts = np.asarray(pts, dtype=np.float32)
    edges: list[tuple[int, int]] = []
    for i in range(n_u):
        for j in range(n_v):
            a = i * n_v + j
            edges.append((a, i * n_v + (j + 1) % n_v))
            edges.append((a, ((i + 1) % n_u) * n_v + j))
    return verts, edges


class WireframeField(EffectField):
    def __init__(self, width, height, settings, seed=None) -> None:
        super().__init__(width, height, settings, seed)
        values = settings.values
        self.rpm = _RPM[values["speed"]]
        self.is_torus = values["shape"] == 1
        short = min(width, height)
        self.proj_scale = short * 0.28
        self.color = np.clip(np.asarray(settings.stops[0], dtype=np.float32) * settings.gain, 0, 255)
        if self.is_torus:
            nu = 12 if short >= 128 else 10
            nv = 8 if short >= 96 else 6
            self.verts, self.edges = _torus_mesh(nu, nv)
        else:
            self.verts, self.edges = _cube_edges()

    def frame(self, t: float, dt: float) -> np.ndarray:
        ang = t * self.rpm * 2 * np.pi / 60.0
        p = _rot_xyz(self.verts, ang * 0.7, ang, ang * 0.45)
        z = p[:, 2] + 3.2
        sx = p[:, 0] / z * self.proj_scale + self.width / 2
        sy = p[:, 1] / z * self.proj_scale + self.height / 2
        out = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        for i, j in self.edges:
            _line(out, sx[i], sy[i], sx[j], sy[j], self.color)
        return out


class WireframeMode(EffectMode):
    mode_id = "wireframe"
    field_class = WireframeField
    tick_interval = 0.04
