"""Attract-mode Pac-Man — generated symmetric mazes, power pellets, chomping, ghosts."""

from __future__ import annotations

import math
from collections import deque

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from display.modes.effect_base import EffectField, EffectMode

_STEP_S = (0.20, 0.13, 0.09, 0.06)  # seconds per tile for Pac-Man
_DIRS = ((1, 0), (0, 1), (-1, 0), (0, -1))
_SCATTER_S, _CHASE_S = 5.0, 14.0
_FRIGHT_S = 6.0
_DEATH_S = 1.6
_CLEAR_S = 2.2
_RELEASE_S = 2.5
_WALL = (40, 70, 255)
_DOT = (255, 190, 160)
_FRIGHT = (50, 60, 255)


def _layout(short: int) -> tuple[int, int]:
    """(tile px, lattice spacing in tiles)."""
    if short < 96:
        return 4, 2
    if short < 160:
        return 6, 3
    return 8, 3


def _generate(nx: int, ny: int, rng: np.random.Generator) -> set:
    """Mirror-symmetric lattice graph with no dead ends; returns open edges."""
    edges = set()
    for j in range(ny):
        for i in range(nx):
            if i + 1 < nx:
                edges.add(((i, j), (i + 1, j)))
            if j + 1 < ny:
                edges.add(((i, j), (i, j + 1)))

    def mirror(e):
        (a, b), (c, d) = e
        m1, m2 = (nx - 1 - a, b), (nx - 1 - c, d)
        return (min(m1, m2), max(m1, m2))

    def degree(node, es):
        return sum(1 for e in es if node in e)

    def connected(es):
        adj: dict = {}
        for a, b in es:
            adj.setdefault(a, []).append(b)
            adj.setdefault(b, []).append(a)
        seen, q = {(0, 0)}, deque([(0, 0)])
        while q:
            for n in adj.get(q.popleft(), ()):
                if n not in seen:
                    seen.add(n)
                    q.append(n)
        return len(seen) == nx * ny

    order = sorted(edges)
    rng.shuffle(order)
    target = int(len(edges) * 0.42)
    removed = 0
    for e in order:
        if removed >= target:
            break
        pair = {e, mirror(e)}
        if not pair <= edges:
            continue
        trial = edges - pair
        nodes = {n for p in pair for n in p}
        if all(degree(n, trial) >= 2 for n in nodes) and connected(trial):
            edges = trial
            removed += len(pair)
    return edges


class _Actor:
    def __init__(self, tile: tuple[int, int], step_s: float) -> None:
        self.cur = self.prev = tile
        self.dir = (1, 0)
        self.step_s = step_s
        self.accum = 0.0

    def pos(self) -> tuple[float, float]:
        a = min(1.0, self.accum / self.step_s)
        return (
            self.prev[0] + (self.cur[0] - self.prev[0]) * a,
            self.prev[1] + (self.cur[1] - self.prev[1]) * a,
        )


class _Ghost(_Actor):
    def __init__(self, tile, step_s, color, corner, release_at) -> None:
        super().__init__(tile, step_s)
        self.color = color
        self.corner = corner
        self.release_at = release_at
        self.frightened = False
        self.eyes = False


class PacmanField(EffectField):
    def __init__(self, width, height, settings, seed=None) -> None:
        super().__init__(width, height, settings, seed)
        self.step_s = _STEP_S[settings.values["speed"]]
        gain = settings.gain
        stops = settings.stops
        self.pac_rgb = tuple(int(c * gain) for c in stops[0])
        self.ghost_rgbs = [tuple(int(c * gain) for c in stops[i % len(stops)]) for i in range(1, 5)]
        self.wall_rgb = tuple(int(c * gain) for c in _WALL)
        self.dot_rgb = tuple(int(c * gain * 0.85) for c in _DOT)
        self.fright_rgb = tuple(int(c * gain) for c in _FRIGHT)
        self.white = tuple(int(235 * gain) for _ in range(3))
        self.tile, self.spacing = _layout(min(width, height))
        s, tl = self.spacing, self.tile
        self.nx = max(3, (width // tl - 3) // s + 1)
        self.ny = max(3, (height // tl - 3) // s + 1)
        self.cols = (self.nx - 1) * s + 3
        self.rows = (self.ny - 1) * s + 3
        self.x_off = (width - self.cols * tl) // 2
        self.y_off = (height - self.rows * tl) // 2
        self._new_level()

    # ------------------------------------------------------------- level

    def _node_tile(self, i: int, j: int) -> tuple[int, int]:
        return 1 + i * self.spacing, 1 + j * self.spacing

    def _new_level(self) -> None:
        edges = _generate(self.nx, self.ny, self.rng)
        open_ = np.zeros((self.rows, self.cols), dtype=bool)
        for (a, b), (c, d) in edges:
            x0, y0 = self._node_tile(a, b)
            x1, y1 = self._node_tile(c, d)
            open_[min(y0, y1) : max(y0, y1) + 1, min(x0, x1) : max(x0, x1) + 1] = True
        self.open = open_
        self.home = self._nearest_open(self.cols // 2, self.rows // 2)
        self.start = self._nearest_open(self.cols // 2, int(self.rows * 0.75))
        self.dots = open_.copy()
        self.dots[self.home[1], self.home[0]] = False
        self.dots[self.start[1], self.start[0]] = False
        self.pellets = set()
        for i, j in ((0, 0), (self.nx - 1, 0), (0, self.ny - 1), (self.nx - 1, self.ny - 1)):
            x, y = self._node_tile(i, j)
            self.pellets.add((x, y))
            self.dots[y, x] = False
        self._render_walls()
        self.board = self.walls_img.copy()
        ys, xs = np.nonzero(self.dots)
        for x, y in zip(xs, ys):
            self._paint_dot(int(x), int(y), self.dot_rgb)
        self.phase = "play"
        self.phase_t = 0.0
        self._reset_actors()

    def _nearest_open(self, x: int, y: int) -> tuple[int, int]:
        ys, xs = np.nonzero(self.open)
        k = int(np.argmin((xs - x) ** 2 + (ys - y) ** 2))
        return int(xs[k]), int(ys[k])

    def _render_walls(self) -> None:
        tl = self.tile
        wall = np.repeat(np.repeat(~self.open, tl, axis=0), tl, axis=1)
        pad = tl
        padded = np.pad(wall, pad, constant_values=True).astype(np.uint8) * 255
        img = Image.fromarray(padded).filter(ImageFilter.GaussianBlur(tl * 0.35))
        solid = np.asarray(img) > 150
        eroded = np.asarray(Image.fromarray(solid.astype(np.uint8) * 255).filter(ImageFilter.MinFilter(3))) > 0
        line = (solid & ~eroded)[pad:-pad, pad:-pad]
        out = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        h, w = line.shape
        region = out[self.y_off : self.y_off + h, self.x_off : self.x_off + w]
        region[line] = self.wall_rgb
        self.walls_img = out

    def _center(self, x: float, y: float) -> tuple[float, float]:
        tl = self.tile
        return self.x_off + (x + 0.5) * tl - 0.5, self.y_off + (y + 0.5) * tl - 0.5

    def _paint_dot(self, x: int, y: int, rgb) -> None:
        cx, cy = self._center(x, y)
        r = 0 if self.tile < 6 else 1
        x0, y0 = int(round(cx - r / 2)), int(round(cy - r / 2))
        self.board[y0 : y0 + r + 1, x0 : x0 + r + 1] = rgb

    def _reset_actors(self) -> None:
        self.pac = _Actor(self.start, self.step_s)
        self.pac.dir = (-1, 0)
        corners = [(self.cols - 2, 1), (1, 1), (self.cols - 2, self.rows - 2), (1, self.rows - 2)]
        self.ghosts = [
            _Ghost(self.home, self.step_s * 1.08, self.ghost_rgbs[i], corners[i], i * _RELEASE_S)
            for i in range(4)
        ]
        self.clock = 0.0
        self.fright_until = -1.0
        self.combo = 0

    # -------------------------------------------------------------- logic

    def _moves(self, tile: tuple[int, int]):
        x, y = tile
        for d in _DIRS:
            nx, ny = x + d[0], y + d[1]
            if 0 <= nx < self.cols and 0 <= ny < self.rows and self.open[ny, nx]:
                yield d, (nx, ny)

    def _bfs(self, start: tuple[int, int]) -> np.ndarray:
        dist = np.full((self.rows, self.cols), 10_000, dtype=np.int32)
        dist[start[1], start[0]] = 0
        q = deque([start])
        while q:
            cur = q.popleft()
            nd = dist[cur[1], cur[0]] + 1
            for _, (nx, ny) in self._moves(cur):
                if dist[ny, nx] > nd:
                    dist[ny, nx] = nd
                    q.append((nx, ny))
        return dist

    def _chase_mode(self) -> bool:
        cycle = self.clock % (_SCATTER_S + _CHASE_S)
        return cycle >= _SCATTER_S

    def _pac_choose(self) -> None:
        pac = self.pac
        food = self.dots.copy()
        for x, y in self.pellets:
            food[y, x] = True
        threats = [g for g in self.ghosts if not g.frightened and not g.eyes and self.clock >= g.release_at]
        prey = [g for g in self.ghosts if g.frightened and not g.eyes]
        best, best_score = pac.dir, math.inf
        for d, tile in self._moves(pac.cur):
            dist = self._bfs(tile)
            score = float(dist[food].min()) if food.any() else 0.0
            if prey:
                score = min(score, min(float(dist[g.cur[1], g.cur[0]]) for g in prey) - 2)
            for g in threats:
                gd = float(dist[g.cur[1], g.cur[0]])
                if gd < 4:
                    score += (4 - gd) * 25
            if d == (-pac.dir[0], -pac.dir[1]):
                score += 1.5
            if score < best_score:
                best, best_score = d, score
        pac.dir = best

    def _ghost_target(self, i: int, g: _Ghost) -> tuple[int, int]:
        if g.eyes:
            return self.home
        if not self._chase_mode():
            return g.corner
        px, py = self.pac.cur
        dx, dy = self.pac.dir
        if i == 0:
            return px, py
        if i == 1:
            return px + 4 * dx, py + 4 * dy
        if i == 2:
            bx, by = self.ghosts[0].cur
            ax, ay = px + 2 * dx, py + 2 * dy
            return 2 * ax - bx, 2 * ay - by
        if abs(g.cur[0] - px) + abs(g.cur[1] - py) > 8:
            return px, py
        return g.corner

    def _ghost_choose(self, i: int, g: _Ghost) -> None:
        options = [(d, t) for d, t in self._moves(g.cur) if d != (-g.dir[0], -g.dir[1])]
        if not options:
            options = list(self._moves(g.cur))
        if g.frightened and not g.eyes:
            g.dir = options[int(self.rng.integers(len(options)))][0]
            return
        tx, ty = self._ghost_target(i, g)
        g.dir = min(options, key=lambda o: (o[1][0] - tx) ** 2 + (o[1][1] - ty) ** 2)[0]

    def _advance(self, actor: _Actor, dt: float, choose) -> None:
        actor.accum += dt
        while actor.accum >= actor.step_s:
            actor.accum -= actor.step_s
            actor.prev = actor.cur
            choose()
            nx, ny = actor.cur[0] + actor.dir[0], actor.cur[1] + actor.dir[1]
            if 0 <= nx < self.cols and 0 <= ny < self.rows and self.open[ny, nx]:
                actor.cur = (nx, ny)
            self._on_step(actor)

    def _on_step(self, actor: _Actor) -> None:
        if actor is self.pac:
            x, y = actor.cur
            if self.dots[y, x]:
                self.dots[y, x] = False
                self._paint_dot(x, y, (0, 0, 0))
            if (x, y) in self.pellets:
                self.pellets.discard((x, y))
                self.fright_until = self.clock + _FRIGHT_S
                self.combo = 0
                for g in self.ghosts:
                    if not g.eyes and self.clock >= g.release_at:
                        g.frightened = True
                        g.dir = (-g.dir[0], -g.dir[1])
        elif isinstance(actor, _Ghost) and actor.eyes and actor.cur == self.home:
            actor.eyes = False
            actor.frightened = False
            actor.step_s = self.step_s * 1.08

    def _collide(self) -> None:
        p = self.pac
        for g in self.ghosts:
            if g.eyes or self.clock < g.release_at:
                continue
            if g.cur == p.cur or (g.cur == p.prev and g.prev == p.cur):
                if g.frightened:
                    g.eyes = True
                    g.frightened = False
                    g.step_s = self.step_s * 0.5
                    self.combo += 1
                else:
                    self.phase, self.phase_t = "death", 0.0
                    return

    def _update(self, dt: float) -> None:
        self.phase_t += dt
        if self.phase == "death":
            if self.phase_t >= _DEATH_S:
                self.phase = "play"
                self._reset_actors()
            return
        if self.phase == "clear":
            if self.phase_t >= _CLEAR_S:
                self._new_level()
            return

        self.clock += dt
        if self.fright_until >= 0 and self.clock >= self.fright_until:
            self.fright_until = -1.0
            for g in self.ghosts:
                g.frightened = False
        self._advance(self.pac, dt, self._pac_choose)
        for i, g in enumerate(self.ghosts):
            if self.clock < g.release_at:
                continue
            step = g.step_s * (1.6 if g.frightened else 1.0)
            g.accum += dt * (g.step_s / step) - dt
            self._advance(g, dt, lambda i=i, g=g: self._ghost_choose(i, g))
        self._collide()
        if not self.dots.any() and not self.pellets:
            self.phase, self.phase_t = "clear", 0.0

    # ------------------------------------------------------------ drawing

    def _draw_pac(self, draw: ImageDraw.ImageDraw, open_frac: float) -> None:
        x, y = self._center(*self.pac.pos())
        r = self.tile * 0.8
        facing = {(1, 0): 0, (0, 1): 90, (-1, 0): 180, (0, -1): 270}[self.pac.dir]
        mouth = 2 + 178 * open_frac
        if mouth >= 179:
            return
        draw.pieslice([x - r, y - r, x + r, y + r], facing + mouth / 2, facing - mouth / 2 + 360, fill=self.pac_rgb)

    def _draw_ghost(self, draw: ImageDraw.ImageDraw, g: _Ghost, t: float) -> None:
        x, y = self._center(*g.pos())
        r = self.tile * 0.8
        if not g.eyes:
            color = g.color
            if g.frightened:
                left = self.fright_until - self.clock
                color = self.white if left < 2.0 and int(t * 6) % 2 else self.fright_rgb
            draw.pieslice([x - r, y - r, x + r, y + r], 180, 360, fill=color)
            draw.rectangle([x - r, y, x + r, y + r * 0.6], fill=color)
            teeth = 3 if self.tile >= 6 else 2
            wave = int(t * 8) % 2
            span = 2 * r / teeth
            for k in range(teeth):
                x0 = x - r + k * span
                if wave:
                    draw.polygon([(x0, y + r * 0.6), (x0 + span, y + r * 0.6), (x0 + span / 2, y + r)], fill=color)
                else:
                    draw.polygon([(x0, y + r * 0.6), (x0 + span / 2, y + r * 0.6), (x0, y + r)], fill=color)
                    draw.polygon([(x0 + span / 2, y + r * 0.6), (x0 + span, y + r * 0.6), (x0 + span, y + r)], fill=color)
            if g.frightened:
                if self.tile >= 6:
                    for ex in (x - r * 0.35, x + r * 0.35):
                        draw.rectangle([ex - 0.5, y - r * 0.3, ex + 0.5, y - r * 0.1], fill=(255, 190, 160))
                return
        dx, dy = g.dir
        if self.tile >= 6:
            er = r * 0.3
            for ex in (x - r * 0.38, x + r * 0.38):
                ey = y - r * 0.2
                draw.ellipse([ex - er, ey - er * 1.2, ex + er, ey + er * 1.2], fill=self.white)
                px, py = ex + dx * er * 0.5, ey + dy * er * 0.6
                pr = er * 0.55
                draw.ellipse([px - pr, py - pr, px + pr, py + pr], fill=(30, 40, 200))
        else:
            for ex in (x - r * 0.45, x + r * 0.45):
                draw.point((ex + dx * 0.5, y - r * 0.25), fill=self.white)

    def frame(self, t: float, dt: float) -> np.ndarray:
        self._update(min(dt, 0.1))
        board = self.board
        if self.phase == "clear" and int(self.phase_t * 4) % 2:
            board = np.where(self.walls_img.any(axis=2, keepdims=True), np.uint8(self.white[0]), self.board)
        img = Image.fromarray(board.copy() if board is self.board else board)
        draw = ImageDraw.Draw(img)
        if int(t * 4) % 2 == 0:
            pr = max(1.0, self.tile * 0.4)
            for x, y in self.pellets:
                cx, cy = self._center(x, y)
                draw.ellipse([cx - pr, cy - pr, cx + pr, cy + pr], fill=self.dot_rgb)
        if self.phase == "death":
            self._draw_pac(draw, min(1.0, self.phase_t / (_DEATH_S * 0.8)))
        elif self.phase == "play":
            for g in self.ghosts:
                self._draw_ghost(draw, g, t)
            self._draw_pac(draw, 0.15 + 0.35 * abs(math.sin(t * 14.0)))
        return np.asarray(img)


class PacmanMode(EffectMode):
    mode_id = "pacman"
    field_class = PacmanField
    tick_interval = 0.03
