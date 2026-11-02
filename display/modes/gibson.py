"""Gibson mode — SCR-derived 10×10 scene with optional single-cell debug.

Full scene: 100 towers at origins ``(x,z)=(0,3,…,27)``, base plane from
resource ``0x72`` (UV 0..10 repeat), fade/mutation state updates paced
independently of the matrix refresh, and dirty-tracked face mosaic caches.

Normal full-scene view uses an SCR interior fly-through camera. Set
``GIBSON_FIXED_CAMERA = True`` for the previous fixed three-quarter framing.
Set ``GIBSON_DEBUG_SINGLE_CELL=1`` to retain the validated one-tower view.

Assets: ``gibson_assets/resource_0x{80,70,72}.png``.
"""

from __future__ import annotations

import math
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image

from display.matrix_config import CANVAS_H, CANVAS_W
from display.modes.gibson_config import (
    resolve_gibson_intensity,
    resolve_gibson_stops,
    resolve_output_gain,
    resolve_speed,
)
from display.pillow_compat import set_pillow_image
from display.state import load_state

Vec3 = Tuple[float, float, float]

FACET_STATE_BYTES = 93
TOWER_COUNT = 100
GRID_N = 10
TILE = 64
ATLAS = 256
CELL_ORIGINS = tuple(range(0, 30, 3))  # 0,3,6,...,27

# SCR local subdivision (macro-cell space).
XZ = (-0.50, -0.17, 0.17, 0.50)
Y = (1.00, 0.67, 0.33, 0.00, -0.33, -0.67, -1.00, -1.33)

BASE_CORNERS: Tuple[Vec3, ...] = (
    (-1.5, -1.34, -1.5),
    (28.5, -1.34, -1.5),
    (28.5, -1.34, 28.5),
    (-1.5, -1.34, 28.5),
)
BASE_UV = ((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0))

FACE_NAMES = ("top", "+Z", "-Z", "-X", "+X")
FACE_FACET_RANGE = {
    "top": (0, 9),
    "+Z": (9, 30),
    "-Z": (30, 51),
    "-X": (51, 72),
    "+X": (72, 93),
}

# State machine pacing — independent of matrix refresh.
STATE_UPDATE_INTERVAL_S = 0.35
TOWER_TOGGLE_EVERY_N_UPDATES = 6

# SCR projection / interior fly-through camera.
VERTICAL_FOV_DEG = 110.0
_Z_NEAR = 0.1
_Z_FAR = 110.0
# Seconds of wall-clock time per 3-unit corridor segment (tune from hardware).
CAMERA_SEGMENT_DURATION_S = 2.25
# Path-parameter lookback so eye trails center along the same spline (1.0 = one segment).
CAMERA_LOOKBACK_SEGMENTS = 0.35
WAYPOINT_XZ = (7.5, 10.5, 13.5, 16.5, 19.5, 22.5)
_WAYPOINT_Y_RANGE = (-0.7, 0.7)
_WAYPOINT_Y_CLAMP = (-0.65, 0.65)
_MOVE_STEPS: Tuple[Tuple[float, float], ...] = (
    (3.0, 0.0),
    (-3.0, 0.0),
    (0.0, 3.0),
    (0.0, -3.0),
)

# Debug: previous fixed three-quarter framing (not an env toggle).
GIBSON_FIXED_CAMERA = False

_ASSETS = Path(__file__).resolve().parent / "gibson_assets"
_TOWER_ATLAS_PATHS = {
    0: _ASSETS / "resource_0x80.png",
    1: _ASSETS / "resource_0x70.png",
}
_BASE_PATH = _ASSETS / "resource_0x72.png"

GIBSON_DEBUG_SINGLE_CELL = os.environ.get("GIBSON_DEBUG_SINGLE_CELL", "").strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)


def _scr_focal_px(viewport_height: float) -> float:
    return (float(viewport_height) * 0.5) / math.tan(math.radians(VERTICAL_FOV_DEG * 0.5))


def _clamp_y(y: float) -> float:
    return float(min(_WAYPOINT_Y_CLAMP[1], max(_WAYPOINT_Y_CLAMP[0], y)))


def _catmull_rom(p0: np.ndarray, p1: np.ndarray, p2: np.ndarray, p3: np.ndarray, u: float) -> np.ndarray:
    """C1 Catmull-Rom; u in [0, 1] interpolates from p1 to p2."""
    u2 = u * u
    u3 = u2 * u
    return 0.5 * (
        (2.0 * p1)
        + (-p0 + p2) * u
        + (2.0 * p0 - 5.0 * p1 + 4.0 * p2 - p3) * u2
        + (-p0 + 3.0 * p1 - 3.0 * p2 + p3) * u3
    )


class GibsonFlythroughCamera:
    """Interior corridor path: axis-aligned ±3 waypoints, Catmull-Rom sample."""

    def __init__(self, rng: np.random.Generator) -> None:
        self._rng = rng
        self._waypoints: List[np.ndarray] = []
        self._last_move: Optional[Tuple[float, float]] = None
        self._path_t = 0.0
        self._last_mono: Optional[float] = None
        self._seed()

    def _random_y(self) -> float:
        return _clamp_y(float(self._rng.uniform(*_WAYPOINT_Y_RANGE)))

    def _in_bounds(self, x: float, z: float) -> bool:
        lo, hi = WAYPOINT_XZ[0], WAYPOINT_XZ[-1]
        return lo - 1e-6 <= x <= hi + 1e-6 and lo - 1e-6 <= z <= hi + 1e-6

    def _next_move(self, x: float, z: float) -> Tuple[float, float]:
        candidates: List[Tuple[float, float]] = []
        reverse: Optional[Tuple[float, float]] = None
        if self._last_move is not None:
            reverse = (-self._last_move[0], -self._last_move[1])
        for dx, dz in _MOVE_STEPS:
            nx, nz = x + dx, z + dz
            if not self._in_bounds(nx, nz):
                continue
            step = (dx, dz)
            if reverse is not None and step == reverse:
                continue
            candidates.append(step)
        if not candidates and reverse is not None:
            rx, rz = reverse
            if self._in_bounds(x + rx, z + rz):
                candidates.append(reverse)
        if not candidates:
            # Should be unreachable on the recovered 6×6 lattice; stay put.
            return (0.0, 0.0)
        return candidates[int(self._rng.integers(0, len(candidates)))]

    def _append_waypoint(self) -> None:
        if not self._waypoints:
            xi = int(self._rng.integers(0, len(WAYPOINT_XZ)))
            zi = int(self._rng.integers(0, len(WAYPOINT_XZ)))
            self._waypoints.append(
                np.array([WAYPOINT_XZ[xi], self._random_y(), WAYPOINT_XZ[zi]], dtype=np.float64)
            )
            return
        x, _y, z = self._waypoints[-1]
        dx, dz = self._next_move(float(x), float(z))
        self._last_move = (dx, dz) if (dx, dz) != (0.0, 0.0) else self._last_move
        self._waypoints.append(np.array([x + dx, self._random_y(), z + dz], dtype=np.float64))

    def _seed(self) -> None:
        while len(self._waypoints) < 6:
            self._append_waypoint()
        # Start with enough history that lookback samples a real segment.
        self._path_t = float(CAMERA_LOOKBACK_SEGMENTS)

    def _ensure_ahead(self, t: float) -> None:
        # Catmull-Rom from P_i→P_{i+1} needs P_{i+2}.
        need = int(math.floor(max(0.0, t))) + 4
        while len(self._waypoints) < need:
            self._append_waypoint()

    def _prune_history(self) -> None:
        # Drop consumed history but keep one pre-segment control point.
        drop = int(math.floor(self._path_t)) - 1
        if drop > 0:
            self._waypoints = self._waypoints[drop:]
            self._path_t -= float(drop)

    def sample(self, t: float) -> np.ndarray:
        t = max(0.0, float(t))
        self._ensure_ahead(t)
        i = int(math.floor(t))
        u = t - float(i)
        n = len(self._waypoints)
        i = min(max(i, 0), n - 2)
        p1 = self._waypoints[i]
        p2 = self._waypoints[min(i + 1, n - 1)]
        p0 = self._waypoints[i - 1] if i > 0 else p1
        p3 = self._waypoints[min(i + 2, n - 1)]
        return _catmull_rom(p0, p1, p2, p3, u)

    def advance(self, now: float) -> Tuple[np.ndarray, np.ndarray]:
        """Advance along the path using wall-clock time; return (eye, center)."""
        if self._last_mono is None:
            self._last_mono = now
        else:
            dt = max(0.0, now - self._last_mono)
            self._last_mono = now
            self._path_t += dt / max(1e-6, CAMERA_SEGMENT_DURATION_S)
        self._ensure_ahead(self._path_t)
        self._prune_history()
        center = self.sample(self._path_t)
        eye = self.sample(max(0.0, self._path_t - CAMERA_LOOKBACK_SEGMENTS))
        center = np.array([center[0], _clamp_y(float(center[1])), center[2]], dtype=np.float64)
        eye = np.array([eye[0], _clamp_y(float(eye[1])), eye[2]], dtype=np.float64)
        return eye, center


def _config_from_state() -> Optional[dict]:
    state = load_state()
    if not state.mode_config:
        return None
    cfg = state.mode_config.get("gibson")
    return cfg if isinstance(cfg, dict) else None


def _pack_facet_byte(atlas_row: int, atlas_col: int, texture_index: int) -> int:
    return (atlas_row & 0x03) | ((atlas_col & 0x03) << 2) | ((texture_index & 0x01) << 4)


def _decode_facet_byte(state: int) -> Tuple[int, int, int]:
    b = int(state) & 0xFF
    return (b & 0x03, (b >> 2) & 0x03, (b >> 4) & 0x01)


def _random_facet_byte(rng: np.random.Generator) -> int:
    return _pack_facet_byte(
        int(rng.integers(0, 4)),
        int(rng.integers(0, 4)),
        int(rng.integers(0, 2)),
    )


def _randomize_facets(rng: np.random.Generator) -> bytearray:
    return bytearray(_random_facet_byte(rng) for _ in range(FACET_STATE_BYTES))


def _facet_face(facet: int) -> str:
    for name, (lo, hi) in FACE_FACET_RANGE.items():
        if lo <= facet < hi:
            return name
    raise IndexError(facet)


def _tower_index(i: int, j: int) -> int:
    return j * GRID_N + i


def _tower_origin(index: int) -> Tuple[float, float]:
    i = index % GRID_N
    j = index // GRID_N
    return float(CELL_ORIGINS[i]), float(CELL_ORIGINS[j])


def _fade_brightness(state: int) -> float:
    fade = int(state) & 0x7F
    return max(0.4, 1.0 - fade * 0.01)


def _load_rgb(path: Path) -> np.ndarray:
    img = Image.open(path).convert("RGB")
    if img.size != (ATLAS, ATLAS):
        img = img.resize((ATLAS, ATLAS), Image.NEAREST)
    return np.asarray(img, dtype=np.uint8)


def _tile_from_atlas(atlas: np.ndarray, row: int, col: int) -> np.ndarray:
    y0, x0 = row * TILE, col * TILE
    return atlas[y0 : y0 + TILE, x0 : x0 + TILE]


def _compose_face(
    facets: bytearray,
    facet_base: int,
    cols: int,
    rows: int,
    atlases: Tuple[np.ndarray, np.ndarray],
) -> np.ndarray:
    face = np.zeros((rows * TILE, cols * TILE, 3), dtype=np.uint8)
    for r in range(rows):
        for c in range(cols):
            atlas_row, atlas_col, tex_i = _decode_facet_byte(facets[facet_base + r * cols + c])
            tile = _tile_from_atlas(atlases[tex_i], atlas_row, atlas_col)
            y0, x0 = r * TILE, c * TILE
            face[y0 : y0 + TILE, x0 : x0 + TILE] = tile
    return face


class GibsonSim:
    """SCR scene state: towers, fade/mutation arrays, paced updates."""

    def __init__(self, *, single_cell: bool) -> None:
        self.single_cell = single_cell
        self.rng = np.random.default_rng()
        n = 1 if single_cell else TOWER_COUNT
        self.tower_count = n
        self.facets: List[bytearray] = [_randomize_facets(self.rng) for _ in range(n)]
        self.tower_fade_state = np.zeros(n, dtype=np.uint8)
        self.tower_mutation_count = np.zeros(n, dtype=np.uint8)
        self._updates = 0
        # Dirty face flags per tower (bit0 top … bit4 +X); all dirty at start.
        self.face_dirty = np.full(n, 0x1F, dtype=np.uint8)

    def mark_face_dirty(self, tower: int, face: str) -> None:
        bit = FACE_NAMES.index(face)
        self.face_dirty[tower] |= 1 << bit

    def clear_face_dirty(self, tower: int, face: str) -> None:
        bit = FACE_NAMES.index(face)
        self.face_dirty[tower] &= ~(1 << bit) & 0x1F

    def is_face_dirty(self, tower: int, face: str) -> bool:
        bit = FACE_NAMES.index(face)
        return bool(self.face_dirty[tower] & (1 << bit))

    def state_update(self) -> None:
        """One SCR-paced state step (not tied to display refresh)."""
        n = self.tower_count
        for t in range(n):
            state = int(self.tower_fade_state[t])
            active = bool(state & 0x80)
            fade = state & 0x7F
            if active:
                fade = min(60, fade + 1)
                self.tower_fade_state[t] = np.uint8(0x80 | fade)
            else:
                fade = max(0, fade - 1)
                self.tower_fade_state[t] = np.uint8(fade)

        self._updates += 1
        if self._updates % TOWER_TOGGLE_EVERY_N_UPDATES == 0:
            t = int(self.rng.integers(0, n))
            state = int(self.tower_fade_state[t])
            if state & 0x80:
                # Toggle inactive.
                fade = state & 0x7F
                self.tower_fade_state[t] = np.uint8(fade)
                self.tower_mutation_count[t] = np.uint8(int(self.rng.integers(0, 4)))
            else:
                fade = state & 0x7F
                self.tower_fade_state[t] = np.uint8(0x80 | fade)
                self.tower_mutation_count[t] = np.uint8(int(self.rng.integers(3, 10)))

        for t in range(n):
            mutations = int(self.tower_mutation_count[t])
            if mutations <= 0:
                continue
            facets = self.facets[t]
            dirty_faces = set()
            for _ in range(mutations):
                idx = int(self.rng.integers(0, FACET_STATE_BYTES))
                facets[idx] = _random_facet_byte(self.rng)
                dirty_faces.add(_facet_face(idx))
            for face in dirty_faces:
                self.mark_face_dirty(t, face)


class GibsonMode:
    tick_interval = 0.016

    def setup(self, matrix) -> None:
        self._matrix = matrix
        self._display_w = CANVAS_W
        self._display_h = CANVAS_H
        self._cx = (self._display_w - 1) * 0.5
        self._cy = (self._display_h - 1) * 0.48
        self._rgb = np.zeros((self._display_h, self._display_w, 3), dtype=np.uint8)
        self._zbuf = np.full((self._display_h, self._display_w), np.inf, dtype=np.float32)
        self._apply_config(_config_from_state())
        self._debug_single = GIBSON_DEBUG_SINGLE_CELL
        self._sim = GibsonSim(single_cell=self._debug_single)
        self._atlases = (
            _load_rgb(_TOWER_ATLAS_PATHS[0]),
            _load_rgb(_TOWER_ATLAS_PATHS[1]),
        )
        self._base_tex = _load_rgb(_BASE_PATH)
        self._face_cache: List[Dict[str, Optional[np.ndarray]]] = [
            {name: None for name in FACE_NAMES} for _ in range(self._sim.tower_count)
        ]
        self._last_state_update = time.monotonic()
        self._state_interval = STATE_UPDATE_INTERVAL_S
        self._fly: Optional[GibsonFlythroughCamera] = None
        if self._debug_single:
            self._focal = 190.0
            self._eye = np.array([1.55, 1.85, -1.55], dtype=np.float64)
            self._target = np.array([0.0, -0.16, 0.0], dtype=np.float64)
        elif GIBSON_FIXED_CAMERA:
            # Previous fixed three-quarter framing (debug fallback).
            self._focal = 210.0
            self._eye = np.array([32.0, 22.0, -16.0], dtype=np.float64)
            self._target = np.array([13.5, 0.0, 13.5], dtype=np.float64)
        else:
            self._focal = _scr_focal_px(self._display_h)
            self._fly = GibsonFlythroughCamera(self._sim.rng)
            self._eye, self._target = self._fly.advance(time.monotonic())
        self._update_basis()

    def teardown(self) -> None:
        pass

    def _apply_config(self, config: Optional[dict]) -> None:
        cfg = dict(config or {})
        self._intensity = resolve_gibson_intensity(cfg)
        self._stops = resolve_gibson_stops(cfg)
        self._speed = resolve_speed(self._intensity)
        self._gain = resolve_output_gain(self._intensity)
        # Intensity gently scales SCR state cadence; display refresh stays separate.
        self._state_interval = STATE_UPDATE_INTERVAL_S / max(0.5, float(self._speed))

    def _update_basis(self) -> None:
        forward = self._target - self._eye
        norm = float(np.linalg.norm(forward))
        if norm < 1e-8:
            forward = np.array([0.0, 0.0, 1.0], dtype=np.float64)
        else:
            forward = forward / norm
        world_up = np.array([0.0, 1.0, 0.0], dtype=np.float64)
        right = np.cross(forward, world_up)
        rnorm = float(np.linalg.norm(right))
        if rnorm < 1e-8:
            right = np.array([1.0, 0.0, 0.0], dtype=np.float64)
        else:
            right = right / rnorm
        up = np.cross(right, forward)
        self._forward = forward
        self._right = right
        self._up = up

    def _update_camera(self) -> None:
        if self._fly is None:
            return
        self._eye, self._target = self._fly.advance(time.monotonic())
        self._update_basis()

    def _maybe_state_update(self) -> None:
        now = time.monotonic()
        if now - self._last_state_update < self._state_interval:
            return
        steps = int((now - self._last_state_update) / self._state_interval)
        steps = max(1, min(steps, 3))
        for _ in range(steps):
            self._sim.state_update()
        self._last_state_update = now

    def _ensure_face(self, tower: int, face: str) -> np.ndarray:
        cached = self._face_cache[tower][face]
        if cached is not None and not self._sim.is_face_dirty(tower, face):
            return cached
        lo, _hi = FACE_FACET_RANGE[face]
        if face == "top":
            tex = _compose_face(self._sim.facets[tower], lo, 3, 3, self._atlases)
        else:
            tex = _compose_face(self._sim.facets[tower], lo, 3, 7, self._atlases)
        self._face_cache[tower][face] = tex
        self._sim.clear_face_dirty(tower, face)
        return tex

    def _project(self, x: float, y: float, z: float) -> Optional[Tuple[float, float, float]]:
        rel = np.array([x, y, z], dtype=np.float64) - self._eye
        cz = float(np.dot(rel, self._forward))
        if cz < _Z_NEAR or cz > _Z_FAR:
            return None
        cx = float(np.dot(rel, self._right))
        cy = float(np.dot(rel, self._up))
        inv = 1.0 / cz
        sx = self._cx + cx * self._focal * inv
        sy = self._cy - cy * self._focal * inv
        return sx, sy, cz

    def _draw_textured_quad(
        self,
        corners: Sequence[Vec3],
        texture: np.ndarray,
        *,
        uvs: Sequence[Tuple[float, float]] = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)),
        brightness: float = 1.0,
        wrap_uv: bool = False,
    ) -> None:
        proj = [self._project(*c) for c in corners]
        if any(p is None for p in proj):
            return
        pts = np.array([(p[0], p[1], p[2]) for p in proj], dtype=np.float64)  # type: ignore[index]
        uv = np.array(uvs, dtype=np.float64)
        th, tw = texture.shape[0], texture.shape[1]

        xs, ys = pts[:, 0], pts[:, 1]
        x_min = max(0, int(np.floor(xs.min())))
        x_max = min(self._display_w - 1, int(np.ceil(xs.max())))
        y_min = max(0, int(np.floor(ys.min())))
        y_max = min(self._display_h - 1, int(np.ceil(ys.max())))
        if x_min > x_max or y_min > y_max:
            return

        yy, xx = np.mgrid[y_min : y_max + 1, x_min : x_max + 1]
        px = xx.astype(np.float64) + 0.5
        py = yy.astype(np.float64) + 0.5
        gain = float(self._gain) * float(brightness)

        def edge(ax, ay, bx, by, px_, py_):
            return (px_ - ax) * (by - ay) - (py_ - ay) * (bx - ax)

        for i0, i1, i2 in ((0, 1, 2), (0, 2, 3)):
            a, b, c = pts[i0], pts[i1], pts[i2]
            area = edge(a[0], a[1], b[0], b[1], c[0], c[1])
            if abs(area) < 1e-6:
                continue
            inv_area = 1.0 / area
            w0 = edge(b[0], b[1], c[0], c[1], px, py) * inv_area
            w1 = edge(c[0], c[1], a[0], a[1], px, py) * inv_area
            w2 = edge(a[0], a[1], b[0], b[1], px, py) * inv_area
            mask = (w0 >= -1e-5) & (w1 >= -1e-5) & (w2 >= -1e-5)
            if not np.any(mask):
                continue
            ua, va = uv[i0]
            ub, vb = uv[i1]
            uc, vc = uv[i2]
            iz_a, iz_b, iz_c = 1.0 / a[2], 1.0 / b[2], 1.0 / c[2]
            inv_z = w0 * iz_a + w1 * iz_b + w2 * iz_c
            mask &= inv_z > 0
            if not np.any(mask):
                continue
            z = np.empty_like(inv_z)
            z[mask] = 1.0 / inv_z[mask]
            zbuf = self._zbuf[y_min : y_max + 1, x_min : x_max + 1]
            mask &= z < zbuf
            if not np.any(mask):
                continue
            u = (w0 * (ua * iz_a) + w1 * (ub * iz_b) + w2 * (uc * iz_c)) * z
            v = (w0 * (va * iz_a) + w1 * (vb * iz_b) + w2 * (vc * iz_c)) * z
            if wrap_uv:
                u_s = np.mod(u, 1.0)
                v_s = np.mod(v, 1.0)
            else:
                mask &= (u >= 0.0) & (v >= 0.0) & (u <= 1.0) & (v <= 1.0)
                if not np.any(mask):
                    continue
                u_s, v_s = u, v
            if not np.any(mask):
                continue
            tx = np.clip((u_s * tw).astype(np.int32), 0, tw - 1)
            ty = np.clip((v_s * th).astype(np.int32), 0, th - 1)
            sample = texture[ty[mask], tx[mask]]
            if gain != 1.0:
                sample = np.clip(sample.astype(np.float32) * gain, 0, 255).astype(np.uint8)
            dest = self._rgb[y_min : y_max + 1, x_min : x_max + 1]
            dest[mask] = sample
            zbuf[mask] = z[mask]

    def _offset_corners(self, local: Sequence[Vec3], ox: float, oz: float) -> List[Vec3]:
        return [(x + ox, y, z + oz) for x, y, z in local]

    def _local_top(self) -> List[Vec3]:
        y = Y[0]
        return [
            (XZ[0], y, XZ[3]),
            (XZ[3], y, XZ[3]),
            (XZ[3], y, XZ[0]),
            (XZ[0], y, XZ[0]),
        ]

    def _local_wall(self, face: str) -> List[Vec3]:
        y_top, y_bot = Y[0], Y[7]
        if face == "+Z":
            z = XZ[3]
            return [
                (XZ[0], y_top, z),
                (XZ[3], y_top, z),
                (XZ[3], y_bot, z),
                (XZ[0], y_bot, z),
            ]
        if face == "-Z":
            z = XZ[0]
            return [
                (XZ[3], y_top, z),
                (XZ[0], y_top, z),
                (XZ[0], y_bot, z),
                (XZ[3], y_bot, z),
            ]
        if face == "+X":
            x = XZ[3]
            return [
                (x, y_top, XZ[3]),
                (x, y_top, XZ[0]),
                (x, y_bot, XZ[0]),
                (x, y_bot, XZ[3]),
            ]
        if face == "-X":
            x = XZ[0]
            return [
                (x, y_top, XZ[0]),
                (x, y_top, XZ[3]),
                (x, y_bot, XZ[3]),
                (x, y_bot, XZ[0]),
            ]
        raise KeyError(face)

    def _draw_base(self) -> None:
        self._draw_textured_quad(
            BASE_CORNERS,
            self._base_tex,
            uvs=BASE_UV,
            brightness=1.0,
            wrap_uv=True,
        )

    def _draw_tower(self, tower: int) -> None:
        if self._debug_single:
            ox, oz = 0.0, 0.0
        else:
            ox, oz = _tower_origin(tower)
        brightness = _fade_brightness(int(self._sim.tower_fade_state[tower]))
        # Far faces first within the tower.
        for face in ("-Z", "-X", "+Z", "+X", "top"):
            tex = self._ensure_face(tower, face)
            if face == "top":
                corners = self._offset_corners(self._local_top(), ox, oz)
            else:
                corners = self._offset_corners(self._local_wall(face), ox, oz)
            self._draw_textured_quad(corners, tex, brightness=brightness)

    def _render(self) -> Image.Image:
        self._rgb[:] = 0
        self._zbuf[:] = np.inf
        if not self._debug_single:
            self._draw_base()
        # Painter sort by camera-space depth of tower origin.
        order: List[Tuple[float, int]] = []
        for t in range(self._sim.tower_count):
            if self._debug_single:
                ox, oz = 0.0, 0.0
            else:
                ox, oz = _tower_origin(t)
            p = self._project(ox, Y[0] * 0.5, oz)
            depth = p[2] if p is not None else 1e9
            order.append((depth, t))
        order.sort(key=lambda item: -item[0])  # far first
        for _depth, t in order:
            self._draw_tower(t)
        return Image.fromarray(self._rgb)

    def tick(self, matrix, canvas):
        self._update_camera()
        self._maybe_state_update()
        frame = self._render()
        set_pillow_image(canvas, frame)
        return matrix.SwapOnVSync(canvas)
