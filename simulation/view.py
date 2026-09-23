"""Rendering: the pixel geometry, a pygame window, an ASCII frame, a GIF recorder.

The pixel geometry lives here as `Layout` because it is a rendering concern, but the input
layer uses the same object, so the cursor lands where it looks like it lands.

pygame and PIL are imported inside functions, so importing this module is safe on a machine
with no display and no rendering dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass

from world import World


@dataclass(frozen=True)
class Layout:
    """Maps arena metres to screen pixels, with the near goal at the bottom of the screen."""

    origin_px: tuple[float, float]      # pixel of arena (0, 0)
    px_per_m: float

    def to_pixels(self, x_m: float, y_m: float) -> tuple[float, float]:
        return self.origin_px[0] + x_m * self.px_per_m, self.origin_px[1] - y_m * self.px_per_m

    def pixel_to_metres(self, px: float, py: float) -> tuple[float, float]:
        return (px - self.origin_px[0]) / self.px_per_m, (self.origin_px[1] - py) / self.px_per_m

    def length_px(self, arena) -> tuple[float, float]:
        return arena.length_m * self.px_per_m, arena.width_m * self.px_per_m

    @classmethod
    def fit_in_rect(cls, arena, rect: tuple[float, float, float, float],
                    margin_px: int = 30) -> "Layout":
        """Fit the table into a region of the window, so a panel can have the rest."""
        x, y, w, h = rect
        usable_w = max(1.0, w - 2 * margin_px)
        usable_h = max(1.0, h - 2 * margin_px)
        scale = min(usable_w / arena.length_m, usable_h / arena.width_m)
        table_w = arena.length_m * scale
        table_h = arena.width_m * scale
        origin_x = x + (w - table_w) / 2.0
        origin_y = y + (h + table_h) / 2.0           # y flipped, near goal at the bottom
        return cls(origin_px=(origin_x, origin_y), px_per_m=scale)

    @classmethod
    def fit(cls, arena, window_w: int, window_h: int, margin_px: int = 40) -> "Layout":
        return cls.fit_in_rect(arena, (0.0, 0.0, float(window_w), float(window_h)), margin_px)


# colours
COL_BACKGROUND = (247, 247, 247)
COL_TABLE = (232, 240, 247)
COL_BORDER = (60, 60, 60)
COL_PUCK = (30, 30, 30)
COL_MALLET_DRIVEN = (200, 40, 40)
COL_MALLET_IDLE = (120, 120, 120)
COL_TARGET = (40, 140, 60)


def draw_scene(screen, world: World, layout: Layout, hud_lines: list[str] | None = None,
               target_m: tuple[float, float] | None = None) -> None:
    """Draw one frame onto a pygame surface. No event handling, no flipping."""
    import pygame

    arena = world.arena
    screen.fill(COL_BACKGROUND)

    x0, y0 = layout.to_pixels(0.0, 0.0)
    w_px, h_px = layout.length_px(arena)
    pygame.draw.rect(screen, COL_TABLE, pygame.Rect(int(x0), int(y0 - h_px), int(w_px), int(h_px)))
    pygame.draw.rect(screen, COL_BORDER, pygame.Rect(int(x0), int(y0 - h_px), int(w_px), int(h_px)), 3)

    # centre line and goal mouths
    mid_x, _ = layout.to_pixels(arena.length_m / 2.0, 0.0)
    pygame.draw.line(screen, (180, 190, 200), (mid_x, y0), (mid_x, y0 - h_px), 2)
    lo_m, hi_m = arena.goal_span_m()
    near_x, near_lo = layout.to_pixels(0.0, lo_m)
    _, near_hi = layout.to_pixels(0.0, hi_m)
    far_x, far_lo = layout.to_pixels(arena.length_m, lo_m)
    _, far_hi = layout.to_pixels(arena.length_m, hi_m)
    pygame.draw.line(screen, (31, 119, 180), (near_x, near_lo), (near_x, near_hi), 6)
    pygame.draw.line(screen, (214, 39, 40), (far_x, far_lo), (far_x, far_hi), 6)

    if target_m is not None:
        tx, ty = layout.to_pixels(*target_m)
        pygame.draw.circle(screen, COL_TARGET, (int(tx), int(ty)), 4)
        pygame.draw.circle(screen, COL_TARGET, (int(tx), int(ty)), 10, 1)

    for i, mallet in enumerate(world.mallets):
        mx, my = layout.to_pixels(mallet.x, mallet.y)
        colour = COL_MALLET_DRIVEN if i == 0 else COL_MALLET_IDLE
        pygame.draw.circle(screen, colour, (int(mx), int(my)),
                           int(mallet.radius * layout.px_per_m), 2)
        pygame.draw.circle(screen, colour, (int(mx), int(my)), 3)

    px, py = layout.to_pixels(world.puck.x, world.puck.y)
    pygame.draw.circle(screen, COL_PUCK, (int(px), int(py)), int(world.puck.radius * layout.px_per_m))

    if hud_lines:
        font = pygame.font.SysFont(None, 20)
        for n, line in enumerate(hud_lines):
            screen.blit(font.render(line, True, (40, 40, 40)), (12, 10 + n * 18))


def hud_lines(world: World, layout: Layout) -> list[str]:
    puck = world.puck
    driven, idle = world.mallets[0], world.mallets[1]
    return [
        f"t {world.t * 1000:7.1f} ms   event {world.event}",
        f"puck    {puck.speed:5.2f} m/s   pos ({puck.x:.3f}, {puck.y:.3f}) m",
        f"mallet0 {driven.speed:5.2f} m/s   pos ({driven.x:.3f}, {driven.y:.3f}) m   "
        f"force ({driven.force_x:6.1f}, {driven.force_y:6.1f}) N",
        f"mallet1 {idle.speed:5.2f} m/s   stationary",
        f"limits  {driven.axial_speed_limit_m_s:.1f} m/s axial, "
        f"{driven.diagonal_speed_limit_m_s:.2f} m/s diagonal",
    ]


def ascii_frame(world: World, cols: int = 78, rows: int = 22) -> str:
    """Terminal render, for logs and headless checks."""
    arena = world.arena
    grid = [[" "] * cols for _ in range(rows)]

    def cell(x_m, y_m):
        c = int(round(x_m / arena.length_m * (cols - 1)))
        r = int(round(y_m / arena.width_m * (rows - 1)))
        return min(max(c, 0), cols - 1), min(max(r, 0), rows - 1)

    for r in range(rows):
        for c in range(cols):
            if r in (0, rows - 1) or c in (0, cols - 1):
                grid[r][c] = "."
    lo, hi = arena.goal_span_m()
    for y_m in (lo, (lo + hi) / 2.0, hi):
        for x_m in (0.0, arena.length_m):
            c, r = cell(x_m, y_m)
            grid[r][c] = "G"
    c, r = cell(world.puck.x, world.puck.y)
    grid[r][c] = "o"
    for i, mallet in enumerate(world.mallets):
        c, r = cell(mallet.x, mallet.y)
        grid[r][c] = "@" if i == 0 else "#"
    head = (f"t {world.t*1000:.0f} ms  puck {world.puck.speed:.2f} m/s  "
            f"mallet0 {world.mallets[0].speed:.2f} m/s  event {world.event}")
    return head + "\n" + "\n".join("".join(row) for row in grid)


class GifRecorder:
    """Collects pygame frames and writes one animated GIF, so a run can be reviewed later."""

    def __init__(self, every: int = 2, max_frames: int = 400):
        self.every = max(1, every)
        self.max_frames = max_frames
        self.frames = []
        self._count = 0

    def maybe_capture(self, screen) -> None:
        self._count += 1
        if self._count % self.every or len(self.frames) >= self.max_frames:
            return
        import pygame
        import numpy as np
        from PIL import Image

        arr = pygame.surfarray.array3d(screen)          # (w, h, 3)
        self.frames.append(Image.fromarray(np.transpose(arr, (1, 0, 2))))

    def save(self, path: str, fps: int = 25) -> str:
        if not self.frames:
            raise ValueError("no frames captured")
        self.frames[0].save(path, save_all=True, append_images=self.frames[1:],
                            duration=int(1000 / fps), loop=0, optimize=True)
        return path
