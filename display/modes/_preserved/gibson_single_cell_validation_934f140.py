"""Gibson mode — temporary single macro-cell validation renderer.

Renders one SCR-derived textured tower (93 facets → five face mosaics) at a
fixed three-quarter camera for geometry / atlas validation. Not the full 10×10
scene. Default *ice* UI config is unused for this revision.

Asset paths: ``gibson_assets/resource_0x80.png`` (texture_index 0) and
``resource_0x70.png`` (texture_index 1). Full-scene note: macro-cell origins
are ``(x,z) = (0,3,6,…,27)``, not cell centers.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image
from rgbmatrix import RGBMatrix

from display.matrix import CANVAS_H, CANVAS_W
from display.modes.gibson_config import (
    resolve_gibson_intensity,
    resolve_gibson_stops,
    resolve_output_gain,
    resolve_speed,
)
from display.pillow_compat import set_pillow_image
from display.state import load_state

Color = Tuple[int, int, int]
Vec3 = Tuple[float, float, float]

FACET_STATE_BYTES = 93
TILE = 64
ATLAS = 256

# SCR local subdivision (macro-cell space).
XZ = (-0.50, -0.17, 0.17, 0.50)
Y = (1.00, 0.67, 0.33, 0.00, -0.33, -0.67, -1.00, -1.33)

# Later full-scene origins (documented; validation cell sits at 0,0).
CELL_ORIGINS = tuple(range(0, 30, 3))  # 0,3,6,...,27

_ASSETS = Path(__file__).resolve().parent / "gibson_assets"
_RESOURCE_PATHS = {
    0: _ASSETS / "resource_0x80.png",
    1: _ASSETS / "resource_0x70.png",
}

_Z_NEAR = 0.2
_Z_FAR = 40.0


def _config_from_state() -> Optional[dict]:
    state = load_state()
    if not state.mode_config:
        return None
    cfg = state.mode_config.get("gibson")
    return cfg if isinstance(cfg, dict) else None


def _pack_facet_byte(atlas_row: int, atlas_col: int, texture_index: int) -> int:
    """SCR facet state: row (2) | col (2) | texture_index (1)."""
    return (atlas_row & 0x03) | ((atlas_col & 0x03) << 2) | ((texture_index & 0x01) << 4)


def _decode_facet_byte(state: int) -> Tuple[int, int, int]:
    b = int(state) & 0xFF
    atlas_row = b & 0x03
    atlas_col = (b >> 2) & 0x03
    texture_index = (b >> 4) & 0x01
    return atlas_row, atlas_col, texture_index


def _randomize_facets(rng: np.random.Generator) -> bytearray:
    """Match original SCR init: independent random atlas_row/col/texture_index."""
    out = bytearray(FACET_STATE_BYTES)
    for i in range(FACET_STATE_BYTES):
        out[i] = _pack_facet_byte(
            int(rng.integers(0, 4)),
            int(rng.integers(0, 4)),
            int(rng.integers(0, 2)),
        )
    return out


class GibsonCell:
    """One SCR macro-cell: 93 packed facet-state bytes."""

    __slots__ = ("facets",)

    def __init__(self, facets: Optional[bytearray] = None) -> None:
        self.facets = facets if facets is not None else bytearray(FACET_STATE_BYTES)

    def decode(self, index: int) -> Tuple[int, int, int]:
        return _decode_facet_byte(self.facets[index])


class GibsonSim:
    """Validation sim: one stationary macro-cell; pulse/grid reserved for later."""

    def __init__(self) -> None:
        rng = np.random.default_rng()
        self.cell = GibsonCell(_randomize_facets(rng))
        # Full-scene origin convention for this tower when scaled back up.
        self.origin_x = 0.0
        self.origin_z = 0.0

    def update(self, _speed: float) -> None:
        # Stationary validation — no orbit, no pulse motion.
        return


def _load_atlases() -> Tuple[np.ndarray, np.ndarray]:
    images: List[np.ndarray] = []
    for idx in (0, 1):
        path = _RESOURCE_PATHS[idx]
        img = Image.open(path).convert("RGB")
        if img.size != (ATLAS, ATLAS):
            img = img.resize((ATLAS, ATLAS), Image.NEAREST)
        images.append(np.asarray(img, dtype=np.uint8))
    return images[0], images[1]


def _tile_from_atlas(atlas: np.ndarray, row: int, col: int) -> np.ndarray:
    y0, x0 = row * TILE, col * TILE
    return atlas[y0 : y0 + TILE, x0 : x0 + TILE]


def _compose_face(
    cell: GibsonCell,
    facet_base: int,
    cols: int,
    rows: int,
    atlases: Tuple[np.ndarray, np.ndarray],
) -> np.ndarray:
    """Build a cols×rows mosaic of 64×64 atlas tiles (row-major facet order)."""
    face = np.zeros((rows * TILE, cols * TILE, 3), dtype=np.uint8)
    for r in range(rows):
        for c in range(cols):
            facet = facet_base + r * cols + c
            atlas_row, atlas_col, tex_i = cell.decode(facet)
            tile = _tile_from_atlas(atlases[tex_i], atlas_row, atlas_col)
            y0, x0 = r * TILE, c * TILE
            face[y0 : y0 + TILE, x0 : x0 + TILE] = tile
    return face


class GibsonMode:
    tick_interval = 0.033  # validation; not chasing 60 fps

    def setup(self, matrix: RGBMatrix) -> None:
        self._matrix = matrix
        self._display_w = CANVAS_W
        self._display_h = CANVAS_H
        self._cx = (self._display_w - 1) * 0.5
        self._cy = (self._display_h - 1) * 0.52
        # Focal chosen so the unit macro-cell lands ~120×120 in the panel.
        self._focal = 190.0
        self._rgb = np.zeros((self._display_h, self._display_w, 3), dtype=np.uint8)
        self._zbuf = np.full((self._display_h, self._display_w), np.inf, dtype=np.float32)
        self._apply_config(_config_from_state())
        self._sim = GibsonSim()
        self._atlases = _load_atlases()
        self._face_textures = self._build_face_textures()
        # Fixed three-quarter camera: top, +Z/front, and +X side visible.
        self._eye = np.array([1.55, 1.85, -1.55], dtype=np.float64)
        self._target = np.array([0.0, -0.16, 0.0], dtype=np.float64)
        self._update_basis()

    def teardown(self) -> None:
        pass

    def _apply_config(self, config: Optional[dict]) -> None:
        cfg = dict(config or {})
        self._intensity = resolve_gibson_intensity(cfg)
        self._stops = resolve_gibson_stops(cfg)
        self._speed = resolve_speed(self._intensity)
        self._gain = resolve_output_gain(self._intensity)

    def _update_basis(self) -> None:
        forward = self._target - self._eye
        forward = forward / np.linalg.norm(forward)
        world_up = np.array([0.0, 1.0, 0.0], dtype=np.float64)
        right = np.cross(forward, world_up)
        right = right / np.linalg.norm(right)
        up = np.cross(right, forward)
        self._forward = forward
        self._right = right
        self._up = up

    def _build_face_textures(self) -> dict:
        cell = self._sim.cell
        atlases = self._atlases
        return {
            "top": _compose_face(cell, 0, 3, 3, atlases),
            "+Z": _compose_face(cell, 9, 3, 7, atlases),
            "-Z": _compose_face(cell, 30, 3, 7, atlases),
            "-X": _compose_face(cell, 51, 3, 7, atlases),
            "+X": _compose_face(cell, 72, 3, 7, atlases),
        }

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
        return sx, sy, cz

    def _draw_textured_quad(
        self,
        corners: Sequence[Vec3],
        texture: np.ndarray,
    ) -> None:
        """Perspective-project a textured quad (corners: TL, TR, BR, BL in UV space)."""
        proj = [self._project(*c) for c in corners]
        if any(p is None for p in proj):
            return
        pts = np.array([(p[0], p[1], p[2]) for p in proj], dtype=np.float64)  # type: ignore[index]
        uvs = np.array([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)], dtype=np.float64)
        th, tw = texture.shape[0], texture.shape[1]

        xs = pts[:, 0]
        ys = pts[:, 1]
        x_min = max(0, int(np.floor(xs.min())))
        x_max = min(self._display_w - 1, int(np.ceil(xs.max())))
        y_min = max(0, int(np.floor(ys.min())))
        y_max = min(self._display_h - 1, int(np.ceil(ys.max())))
        if x_min > x_max or y_min > y_max:
            return

        yy, xx = np.mgrid[y_min : y_max + 1, x_min : x_max + 1]
        px = xx.astype(np.float64) + 0.5
        py = yy.astype(np.float64) + 0.5
        gain = float(self._gain)

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
            ua, va = uvs[i0]
            ub, vb = uvs[i1]
            uc, vc = uvs[i2]
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
            mask &= (u >= 0.0) & (v >= 0.0) & (u <= 1.0) & (v <= 1.0)
            if not np.any(mask):
                continue
            tx = np.clip((u * (tw - 1)).astype(np.int32), 0, tw - 1)
            ty = np.clip((v * (th - 1)).astype(np.int32), 0, th - 1)
            sample = texture[ty[mask], tx[mask]]
            if gain < 1.0:
                sample = (sample.astype(np.float32) * gain).astype(np.uint8)
            dest = self._rgb[y_min : y_max + 1, x_min : x_max + 1]
            dest[mask] = sample
            zbuf[mask] = z[mask]

    def _macro_corners_top(self) -> List[Vec3]:
        # TL(-X,+Z), TR(+X,+Z), BR(+X,-Z), BL(-X,-Z) at y = Y[0]
        y = Y[0]
        return [
            (XZ[0], y, XZ[3]),
            (XZ[3], y, XZ[3]),
            (XZ[3], y, XZ[0]),
            (XZ[0], y, XZ[0]),
        ]

    def _macro_corners_wall(self, face: str) -> List[Vec3]:
        """Wall corners TL, TR, BR, BL with UV origin at top-left of mosaic."""
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
            # Flip X so outward-facing UV still left→right when viewed from -Z.
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

    def _render(self) -> Image.Image:
        self._rgb[:] = 0
        self._zbuf[:] = np.inf
        tex = self._face_textures
        # Painter-ish order: far walls first, then near walls, top last.
        # Camera sees +Z and +X; draw -Z/-X first.
        self._draw_textured_quad(self._macro_corners_wall("-Z"), tex["-Z"])
        self._draw_textured_quad(self._macro_corners_wall("-X"), tex["-X"])
        self._draw_textured_quad(self._macro_corners_wall("+Z"), tex["+Z"])
        self._draw_textured_quad(self._macro_corners_wall("+X"), tex["+X"])
        self._draw_textured_quad(self._macro_corners_top(), tex["top"])
        return Image.fromarray(self._rgb)

    def tick(self, matrix: RGBMatrix, canvas):
        self._sim.update(self._speed)
        frame = self._render()
        set_pillow_image(canvas, frame)
        return matrix.SwapOnVSync(canvas)
