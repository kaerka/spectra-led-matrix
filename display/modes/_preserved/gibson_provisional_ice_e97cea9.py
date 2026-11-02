"""Preserved provisional Gibson ICE renderer (commit e97cea9).

Frozen snapshot before SCR-derived 10×10 scene model. Not imported by the
live mode registry — kept for rollback / comparison.
"""

"""Original module docstring (provisional ICE):

Gibson mode — Neuromancer matrix fly-through on the 192×192 wall.

Infinite transparent chessboard, pale neon grid, ICE constructs, and
data packets. Default *ice* palette is green-weighted cyan so HUB75 and
the Iris preview do not wash to magenta.

"""
from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np
from PIL import Image
from rgbmatrix import RGBMatrix

from display.matrix import CANVAS_H, CANVAS_W
from display.modes.gibson_config import (
    resolve_draw_ceiling,
    resolve_gibson_intensity,
    resolve_gibson_stops,
    resolve_ice_count,
    resolve_output_gain,
    resolve_packet_count,
    resolve_speed,
    resolve_x_lines,
)
from display.pillow_compat import set_pillow_image
from display.state import load_state

Color = Tuple[int, int, int]

_Z_NEAR = 0.16
_Z_FAR = 2.55
_FLOOR_Y = 0.58
_CEIL_Y = -0.52
_GRID_SPACING = 0.22
_XY_SPAN = 1.65


def _config_from_state() -> Optional[dict]:
    state = load_state()
    if not state.mode_config:
        return None
    cfg = state.mode_config.get("gibson")
    return cfg if isinstance(cfg, dict) else None


def _shade(color: Color, t: float) -> Color:
    t = max(0.0, min(1.0, t))
    return (int(color[0] * t), int(color[1] * t), int(color[2] * t))


class GibsonSim:
    def __init__(self, ice_count: int, packet_count: int) -> None:
        self.scroll = 0.0
        self.ice_count = max(1, ice_count)
        self.packet_count = max(1, packet_count)
        rng = np.random.default_rng()
        self.ice_x = (rng.random(self.ice_count) * 2.0 - 1.0) * 1.15
        self.ice_z = rng.random(self.ice_count) * (_Z_FAR - 0.45) + 0.45
        self.ice_w = rng.random(self.ice_count) * 0.16 + 0.10
        self.ice_d = rng.random(self.ice_count) * 0.18 + 0.10
        self.ice_h = rng.random(self.ice_count) * 0.42 + 0.16
        self.pkt_x = (rng.integers(0, 9, self.packet_count) - 4) * _GRID_SPACING
        self.pkt_z = rng.random(self.packet_count) * (_Z_FAR - _Z_NEAR) + _Z_NEAR
        self.pkt_speed = rng.random(self.packet_count) * 0.55 + 0.35

    def resize(self, ice_count: int, packet_count: int) -> None:
        if ice_count == self.ice_count and packet_count == self.packet_count:
            return
        self.__init__(ice_count, packet_count)

    def update(self, speed: float) -> None:
        step = 0.018 * speed
        self.scroll = (self.scroll + step) % _GRID_SPACING
        self.ice_z -= step
        dead = self.ice_z <= _Z_NEAR
        if np.any(dead):
            n = int(np.count_nonzero(dead))
            rng = np.random.default_rng()
            idx = np.flatnonzero(dead)
            self.ice_x[idx] = (rng.random(n) * 2.0 - 1.0) * 1.15
            self.ice_z[idx] = _Z_FAR - rng.random(n) * 0.2
            self.ice_w[idx] = rng.random(n) * 0.16 + 0.10
            self.ice_d[idx] = rng.random(n) * 0.18 + 0.10
            self.ice_h[idx] = rng.random(n) * 0.42 + 0.16
        self.pkt_z -= step * self.pkt_speed
        pdead = self.pkt_z <= _Z_NEAR
        if np.any(pdead):
            n = int(np.count_nonzero(pdead))
            rng = np.random.default_rng()
            idx = np.flatnonzero(pdead)
            self.pkt_x[idx] = (rng.integers(0, 9, n) - 4) * _GRID_SPACING
            self.pkt_z[idx] = _Z_FAR - rng.random(n) * 0.15


class GibsonMode:
    tick_interval = 0.016

    def setup(self, matrix: RGBMatrix) -> None:
        self._matrix = matrix
        self._display_w = CANVAS_W
        self._display_h = CANVAS_H
        self._cx = (self._display_w - 1) * 0.5
        self._horizon = self._display_h * 0.38
        self._focal = min(self._display_w, self._display_h) * 0.62
        self._rgb = np.zeros((self._display_h, self._display_w, 3), dtype=np.uint8)
        self._apply_config(_config_from_state())
        self._sim = GibsonSim(self._ice_count, self._packet_count)

    def teardown(self) -> None:
        pass

    def _apply_config(self, config: Optional[dict]) -> None:
        cfg = dict(config or {})
        self._intensity = resolve_gibson_intensity(cfg)
        self._stops = resolve_gibson_stops(cfg)
        self._speed = resolve_speed(self._intensity)
        self._gain = resolve_output_gain(self._intensity)
        self._x_lines = resolve_x_lines(self._intensity)
        self._ice_count = resolve_ice_count(self._intensity)
        self._packet_count = resolve_packet_count(self._intensity)
        self._draw_ceiling = resolve_draw_ceiling(self._intensity)

    def _project(self, x: float, y: float, z: float) -> Optional[Tuple[float, float, float]]:
        if z < _Z_NEAR:
            return None
        inv = 1.0 / z
        sx = self._cx + x * self._focal * inv
        sy = self._horizon + y * self._focal * inv
        depth = 1.0 - (z - _Z_NEAR) / (_Z_FAR - _Z_NEAR)
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
            # Convex: outermost pair spans the silhouette.
            x_left = max(0, int(np.floor(xs[0])))
            x_right = min(self._display_w - 1, int(np.ceil(xs[-1])))
            if x_left > x_right:
                continue
            np.maximum(
                self._rgb[y, x_left : x_right + 1],
                fill,
                out=self._rgb[y, x_left : x_right + 1],
            )

    def _line(self, a: Optional[Tuple[float, float, float]], b: Optional[Tuple[float, float, float]], color: Color) -> None:
        if a is None or b is None:
            return
        x0, y0, d0 = a
        x1, y1, d1 = b
        steps = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
        if steps > 280:
            steps = 280
        for i in range(steps + 1):
            t = i / steps
            x = int(round(x0 + (x1 - x0) * t))
            y = int(round(y0 + (y1 - y0) * t))
            d = d0 + (d1 - d0) * t
            fog = 0.18 + 0.82 * d
            self._plot(x, y, _shade(color, fog * self._gain))

    def _box(self, x: float, z: float, w: float, d: float, h: float, color: Color) -> None:
        x0, x1 = x - w * 0.5, x + w * 0.5
        z0, z1 = z, z + d
        y0, y1 = _FLOOR_Y, _FLOOR_Y - h
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
        # Faces: far / left / right / top / near. Strengths for first hardware test.
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
        # Painter: farther (lower projected depth) first.
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

    def _grid_zs(self) -> List[float]:
        zs = []
        z = _Z_NEAR + (_GRID_SPACING - self._sim.scroll)
        while z <= _Z_FAR:
            zs.append(z)
            z += _GRID_SPACING
        return zs

    def _grid_xs(self) -> List[float]:
        half = self._x_lines // 2
        return [(i - half) * _GRID_SPACING for i in range(self._x_lines)]

    def _draw_plane(self, y: float, color: Color, gain: float) -> None:
        xs = self._grid_xs()
        zs = self._grid_zs()
        dim = _shade(color, gain)
        for z in zs:
            left = self._project(-_XY_SPAN, y, z)
            right = self._project(_XY_SPAN, y, z)
            self._line(left, right, dim)
        for x in xs:
            near = self._project(x, y, _Z_NEAR + 0.02)
            far = self._project(x, y, _Z_FAR)
            self._line(near, far, dim)

    def _horizon_glow(self) -> None:
        color = self._stops["grid"]
        y = int(round(self._horizon))
        for dy in range(-2, 3):
            py = y + dy
            if py < 0 or py >= self._display_h:
                continue
            fall = 0.55 if dy == 0 else 0.22 / (abs(dy) + 0.4)
            row = _shade(color, fall * self._gain * 0.55)
            for x in range(self._display_w):
                self._plot(x, py, row)

    def _render(self) -> Image.Image:
        self._rgb[:] = 0
        self._horizon_glow()
        self._draw_plane(_FLOOR_Y, self._stops["grid"], 1.0)
        if self._draw_ceiling:
            self._draw_plane(_CEIL_Y, self._stops["grid"], 0.42)
        ice = self._stops["ice"]
        order = np.argsort(-self._sim.ice_z)
        for i in order:
            self._box(
                float(self._sim.ice_x[i]),
                float(self._sim.ice_z[i]),
                float(self._sim.ice_w[i]),
                float(self._sim.ice_d[i]),
                float(self._sim.ice_h[i]),
                ice,
            )
        node = self._stops["node"]
        for i in range(self._sim.packet_count):
            p = self._project(float(self._sim.pkt_x[i]), _FLOOR_Y - 0.04, float(self._sim.pkt_z[i]))
            if p is None:
                continue
            x, y, d = p
            xi, yi = int(round(x)), int(round(y))
            bright = _shade(node, (0.35 + 0.65 * d) * self._gain)
            for dx, dy in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)):
                self._plot(xi + dx, yi + dy, bright if dx == 0 and dy == 0 else _shade(bright, 0.45))
        # Soft phosphor scan — odd rows slightly dimmer, reads as deck CRT.
        self._rgb[1::2] = (self._rgb[1::2].astype(np.uint16) * 82 // 100).astype(np.uint8)
        return Image.fromarray(self._rgb)

    def tick(self, matrix: RGBMatrix, canvas):
        self._sim.update(self._speed)
        frame = self._render()
        set_pillow_image(canvas, frame)
        return matrix.SwapOnVSync(canvas)
