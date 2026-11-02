"""Gibson mode — SCR-derived 10×10 Neuromancer scene on the 192×192 wall.

World spacing is 3.0 units (30×30 footprint). Each cell holds 93 packed
facet-state bytes (three 2-bit fields per byte); the exact 93-facet mesh is
recovered separately, so cells currently draw simplified placeholder boxes.
A base plane and X/Z pulses complete the provisional architecture.

Default *ice* palette stays green-weighted cyan for HUB75 / Iris.
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

import numpy as np
from PIL import Image
from rgbmatrix import RGBMatrix

from display.matrix import CANVAS_H, CANVAS_W
from display.modes.gibson_config import (
    resolve_gibson_intensity,
    resolve_gibson_stops,
    resolve_output_gain,
    resolve_packet_count,
    resolve_speed,
)
from display.pillow_compat import set_pillow_image
from display.state import load_state

Color = Tuple[int, int, int]

# SCR scene constants (world units).
CELL_SPACING = 3.0
GRID_N = 10
FACET_STATE_BYTES = 93
BASE_Y = -1.34
BASE_MIN = (-1.5, BASE_Y, -1.5)
BASE_MAX = (28.5, BASE_Y, 28.5)
WORLD_MIN = 0.0
WORLD_MAX = 30.0

# Placeholder cell prism (not the recovered 93-facet mesh).
PLACEHOLDER_W = 2.0
PLACEHOLDER_D = 2.0
PLACEHOLDER_H = 1.15

# Pulse directions: 0=+X, 1=+Z, 2=-X, 3=-Z.
_PULSE_DIRS: Tuple[Tuple[float, float], ...] = (
    (1.0, 0.0),
    (0.0, 1.0),
    (-1.0, 0.0),
    (0.0, -1.0),
)

# Soft near-plane for perspective; far clip beyond the scene diagonal.
_Z_NEAR = 0.35
_Z_FAR = 80.0


def _config_from_state() -> Optional[dict]:
    state = load_state()
    if not state.mode_config:
        return None
    cfg = state.mode_config.get("gibson")
    return cfg if isinstance(cfg, dict) else None


def _shade(color: Color, t: float) -> Color:
    t = max(0.0, min(1.0, t))
    return (int(color[0] * t), int(color[1] * t), int(color[2] * t))


def _pack_facet_byte(field0: int, field1: int, field2: int) -> int:
    """Pack three 2-bit fields into one facet-state byte (bits 0–5)."""
    return (field0 & 0x03) | ((field1 & 0x03) << 2) | ((field2 & 0x03) << 4)


def _unpack_facet_byte(value: int) -> Tuple[int, int, int]:
    """Return (field0, field1, field2) from a packed facet-state byte."""
    b = int(value) & 0xFF
    return (b & 0x03, (b >> 2) & 0x03, (b >> 4) & 0x03)


class GibsonCell:
    """One SCR grid cell: 93 packed facet-state bytes, three 2-bit fields each."""

    __slots__ = ("facets",)

    def __init__(self) -> None:
        # Architecture placeholder — not expanded into ad-hoc attributes.
        self.facets = bytearray(FACET_STATE_BYTES)

    def facet_fields(self, index: int) -> Tuple[int, int, int]:
        return _unpack_facet_byte(self.facets[index])

    def set_facet_fields(self, index: int, field0: int, field1: int, field2: int) -> None:
        self.facets[index] = _pack_facet_byte(field0, field1, field2)


class GibsonPulse:
    """Travelling pulse — moves on X/Z; direction is 0–3."""

    __slots__ = ("x", "y", "z", "direction")

    def __init__(self, x: float, y: float, z: float, direction: int) -> None:
        self.x = float(x)
        self.y = float(y)
        self.z = float(z)
        self.direction = int(direction) & 0x03

    def update(self, step: float) -> None:
        dx, dz = _PULSE_DIRS[self.direction]
        self.x += dx * step
        self.z += dz * step
        # Bounce within roughly 0–30 world bounds.
        if self.x < WORLD_MIN:
            self.x = WORLD_MIN
            self.direction = 0  # +X
        elif self.x > WORLD_MAX:
            self.x = WORLD_MAX
            self.direction = 2  # -X
        if self.z < WORLD_MIN:
            self.z = WORLD_MIN
            self.direction = 1  # +Z
        elif self.z > WORLD_MAX:
            self.z = WORLD_MAX
            self.direction = 3  # -Z


class GibsonSim:
    """Fixed 10×10 SCR scene: cells, base plane extents, and pulses."""

    def __init__(self, pulse_count: int) -> None:
        self.cells: List[List[GibsonCell]] = [
            [GibsonCell() for _ in range(GRID_N)] for _ in range(GRID_N)
        ]
        self.cam_angle = 0.35
        self.pulses: List[GibsonPulse] = []
        self._spawn_pulses(max(1, pulse_count))

    def _spawn_pulses(self, count: int) -> None:
        rng = np.random.default_rng()
        self.pulses = []
        for _ in range(count):
            self.pulses.append(
                GibsonPulse(
                    x=float(rng.uniform(2.0, 28.0)),
                    y=BASE_Y + 0.55,
                    z=float(rng.uniform(2.0, 28.0)),
                    direction=int(rng.integers(0, 4)),
                )
            )

    def resize_pulses(self, pulse_count: int) -> None:
        count = max(1, pulse_count)
        if len(self.pulses) == count:
            return
        self._spawn_pulses(count)

    def cell_origin(self, i: int, j: int) -> Tuple[float, float, float]:
        """World-space center of cell (i, j) on the base plane."""
        return (
            i * CELL_SPACING + CELL_SPACING * 0.5,
            BASE_Y,
            j * CELL_SPACING + CELL_SPACING * 0.5,
        )

    def update(self, speed: float) -> None:
        self.cam_angle = (self.cam_angle + 0.0045 * speed) % (math.tau)
        pulse_step = 0.055 * speed
        for pulse in self.pulses:
            pulse.update(pulse_step)


class GibsonMode:
    tick_interval = 0.016

    def setup(self, matrix: RGBMatrix) -> None:
        self._matrix = matrix
        self._display_w = CANVAS_W
        self._display_h = CANVAS_H
        self._cx = (self._display_w - 1) * 0.5
        self._cy = (self._display_h - 1) * 0.42
        self._focal = min(self._display_w, self._display_h) * 0.95
        self._rgb = np.zeros((self._display_h, self._display_w, 3), dtype=np.uint8)
        self._apply_config(_config_from_state())
        self._sim = GibsonSim(self._pulse_count)
        self._eye = np.zeros(3, dtype=np.float64)
        self._right = np.zeros(3, dtype=np.float64)
        self._up = np.zeros(3, dtype=np.float64)
        self._forward = np.zeros(3, dtype=np.float64)

    def teardown(self) -> None:
        pass

    def _apply_config(self, config: Optional[dict]) -> None:
        cfg = dict(config or {})
        self._intensity = resolve_gibson_intensity(cfg)
        self._stops = resolve_gibson_stops(cfg)
        self._speed = resolve_speed(self._intensity)
        self._gain = resolve_output_gain(self._intensity)
        # Reuse packet intensity ladder as pulse count (UI unchanged).
        self._pulse_count = resolve_packet_count(self._intensity)

    def _update_camera(self) -> None:
        target = np.array([13.5, BASE_Y + 0.4, 13.5], dtype=np.float64)
        radius = 26.0
        angle = self._sim.cam_angle
        eye = np.array(
            [
                target[0] + radius * math.cos(angle),
                12.5,
                target[2] + radius * math.sin(angle),
            ],
            dtype=np.float64,
        )
        forward = target - eye
        norm = np.linalg.norm(forward)
        if norm < 1e-6:
            forward = np.array([0.0, 0.0, 1.0])
        else:
            forward = forward / norm
        world_up = np.array([0.0, 1.0, 0.0], dtype=np.float64)
        right = np.cross(forward, world_up)
        rnorm = np.linalg.norm(right)
        if rnorm < 1e-6:
            right = np.array([1.0, 0.0, 0.0])
        else:
            right = right / rnorm
        up = np.cross(right, forward)
        self._eye = eye
        self._forward = forward
        self._right = right
        self._up = up

    def _project(self, x: float, y: float, z: float) -> Optional[Tuple[float, float, float]]:
        rel = np.array([x, y, z], dtype=np.float64) - self._eye
        cz = float(np.dot(rel, self._forward))
        if cz < _Z_NEAR:
            return None
        cx = float(np.dot(rel, self._right))
        cy = float(np.dot(rel, self._up))
        inv = 1.0 / cz
        sx = self._cx + cx * self._focal * inv
        sy = self._cy - cy * self._focal * inv
        depth = 1.0 - (cz - _Z_NEAR) / (_Z_FAR - _Z_NEAR)
        return sx, sy, max(0.0, min(1.0, depth))

    def _plot(self, x: int, y: int, color: Color) -> None:
        if 0 <= x < self._display_w and 0 <= y < self._display_h:
            self._rgb[y, x] = (
                max(self._rgb[y, x, 0], color[0]),
                max(self._rgb[y, x, 1], color[1]),
                max(self._rgb[y, x, 2], color[2]),
            )

    def _fill_convex(self, verts: List[Tuple[float, float, float]], color: Color) -> None:
        """Scanline-fill a convex projected polygon into ``_rgb`` via ``np.maximum``."""
        if len(verts) < 3:
            return
        pts = [(float(v[0]), float(v[1])) for v in verts]
        ys = [p[1] for p in pts]
        y_min = max(0, int(np.floor(min(ys))))
        y_max = min(self._display_h - 1, int(np.ceil(max(ys))))
        if y_min > y_max:
            return
        n = len(pts)
        fill = np.array(color, dtype=np.uint8)
        for y in range(y_min, y_max + 1):
            y_mid = y + 0.5
            xs: List[float] = []
            for i in range(n):
                x0, y0 = pts[i]
                x1, y1 = pts[(i + 1) % n]
                if y0 == y1:
                    continue
                if y0 > y1:
                    x0, y0, x1, y1 = x1, y1, x0, y0
                if y_mid < y0 or y_mid >= y1:
                    continue
                t = (y_mid - y0) / (y1 - y0)
                xs.append(x0 + (x1 - x0) * t)
            if len(xs) < 2:
                continue
            xs.sort()
            x_left = max(0, int(np.floor(xs[0])))
            x_right = min(self._display_w - 1, int(np.ceil(xs[-1])))
            if x_left > x_right:
                continue
            np.maximum(
                self._rgb[y, x_left : x_right + 1],
                fill,
                out=self._rgb[y, x_left : x_right + 1],
            )

    def _line(
        self,
        a: Optional[Tuple[float, float, float]],
        b: Optional[Tuple[float, float, float]],
        color: Color,
    ) -> None:
        if a is None or b is None:
            return
        x0, y0, d0 = a
        x1, y1, d1 = b
        steps = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
        if steps > 320:
            steps = 320
        for i in range(steps + 1):
            t = i / steps
            x = int(round(x0 + (x1 - x0) * t))
            y = int(round(y0 + (y1 - y0) * t))
            d = d0 + (d1 - d0) * t
            fog = 0.18 + 0.82 * d
            self._plot(x, y, _shade(color, fog * self._gain))

    def _box(
        self,
        cx: float,
        floor_y: float,
        cz: float,
        w: float,
        d: float,
        h: float,
        color: Color,
    ) -> None:
        """Axis-aligned prism; Y-up world (floor at ``floor_y``, top at ``floor_y + h``)."""
        x0, x1 = cx - w * 0.5, cx + w * 0.5
        z0, z1 = cz - d * 0.5, cz + d * 0.5
        y0, y1 = floor_y, floor_y + h
        corners = [
            (x0, y0, z0),
            (x1, y0, z0),
            (x1, y0, z1),
            (x0, y0, z1),
            (x0, y1, z0),
            (x1, y1, z0),
            (x1, y1, z1),
            (x0, y1, z1),
        ]
        proj = [self._project(*c) for c in corners]
        face_defs = (
            ("far", (2, 3, 7, 6), 0.16),
            ("left", (0, 3, 7, 4), 0.24),
            ("right", (1, 2, 6, 5), 0.30),
            ("top", (4, 5, 6, 7), 0.46),
            ("near", (0, 1, 5, 4), 0.38),
        )
        faces = []
        for _name, idxs, strength in face_defs:
            verts = [proj[i] for i in idxs]
            if any(v is None for v in verts):
                continue
            avg_depth = sum(v[2] for v in verts) / 4.0  # type: ignore[index]
            faces.append((avg_depth, verts, strength))
        faces.sort(key=lambda item: item[0])
        for avg_depth, verts, strength in faces:
            fog = 0.18 + 0.82 * avg_depth
            fill_color = _shade(color, fog * self._gain * strength)
            self._fill_convex(verts, fill_color)  # type: ignore[arg-type]
        edges = (
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
        )
        for i, j in edges:
            self._line(proj[i], proj[j], color)

    def _draw_base_plane(self) -> None:
        """Recovered SCR base plane + 10×10 cell grid lines (not infinite scroll)."""
        x0, y, z0 = BASE_MIN
        x1, _, z1 = BASE_MAX
        corners = [
            self._project(x0, y, z0),
            self._project(x1, y, z0),
            self._project(x1, y, z1),
            self._project(x0, y, z1),
        ]
        if not any(v is None for v in corners):
            avg_depth = sum(v[2] for v in corners) / 4.0  # type: ignore[index]
            fog = 0.18 + 0.82 * avg_depth
            fill = _shade(self._stops["grid"], fog * self._gain * 0.14)
            self._fill_convex(corners, fill)  # type: ignore[arg-type]
            edge = _shade(self._stops["grid"], fog * self._gain * 0.55)
            for a, b in ((0, 1), (1, 2), (2, 3), (3, 0)):
                self._line(corners[a], corners[b], edge)

        line = self._stops["grid"]
        for i in range(GRID_N + 1):
            t = i * CELL_SPACING
            # lines parallel to X at z = t (within base), and parallel to Z at x = t
            xa0, xa1 = BASE_MIN[0], BASE_MAX[0]
            za0, za1 = BASE_MIN[2], BASE_MAX[2]
            if 0 <= t <= 30:
                self._line(
                    self._project(xa0, BASE_Y, t),
                    self._project(xa1, BASE_Y, t),
                    line,
                )
                self._line(
                    self._project(t, BASE_Y, za0),
                    self._project(t, BASE_Y, za1),
                    line,
                )

    def _draw_placeholder_cells(self) -> None:
        ice = self._stops["ice"]
        # Painter: farther cells first (by camera-space depth of cell center).
        order: List[Tuple[float, int, int]] = []
        for j in range(GRID_N):
            for i in range(GRID_N):
                cx, cy, cz = self._sim.cell_origin(i, j)
                p = self._project(cx, cy + PLACEHOLDER_H * 0.5, cz)
                depth = p[2] if p is not None else -1.0
                order.append((depth, i, j))
        order.sort(key=lambda item: item[0])
        for _depth, i, j in order:
            cx, cy, cz = self._sim.cell_origin(i, j)
            # Facet buffer is live architecture; geometry stays a simple prism.
            _ = self._sim.cells[i][j].facets
            self._box(cx, cy, cz, PLACEHOLDER_W, PLACEHOLDER_D, PLACEHOLDER_H, ice)

    def _draw_pulses(self) -> None:
        node = self._stops["node"]
        for pulse in self._sim.pulses:
            p = self._project(pulse.x, pulse.y, pulse.z)
            if p is None:
                continue
            x, y, d = p
            xi, yi = int(round(x)), int(round(y))
            bright = _shade(node, (0.40 + 0.60 * d) * self._gain)
            for dx, dy in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1)):
                fall = 1.0 if dx == 0 and dy == 0 else 0.45
                self._plot(xi + dx, yi + dy, _shade(bright, fall))

    def _render(self) -> Image.Image:
        self._rgb[:] = 0
        self._update_camera()
        self._draw_base_plane()
        self._draw_placeholder_cells()
        self._draw_pulses()
        # Soft phosphor scan — odd rows slightly dimmer, reads as deck CRT.
        self._rgb[1::2] = (self._rgb[1::2].astype(np.uint16) * 82 // 100).astype(np.uint8)
        return Image.fromarray(self._rgb)

    def tick(self, matrix: RGBMatrix, canvas):
        self._sim.resize_pulses(self._pulse_count)
        self._sim.update(self._speed)
        frame = self._render()
        set_pillow_image(canvas, frame)
        return matrix.SwapOnVSync(canvas)
