"""Pure physics for the air hockey simulator. No rclpy, no parameters, no clocks.

The node owns the ROS interfaces and forwards numbers here, which is what lets the puck and
mallet behaviour be tested without a running ROS graph.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


@dataclass(frozen=True)
class Bounds:
    x_min: float
    x_max: float
    y_min: float
    y_max: float


def step_puck(
    px: float,
    py: float,
    vx: float,
    vy: float,
    drag: float,
    dt: float,
) -> tuple[float, float, float, float]:
    """Advance the puck by dt with an exponential drag term, then its position."""
    vx *= math.exp(-drag * dt)
    vy *= math.exp(-drag * dt)
    px += vx * dt
    py += vy * dt
    return px, py, vx, vy


def bounce_off_walls(
    x: float,
    y: float,
    vx: float,
    vy: float,
    puck_r: float,
    bounds: Bounds,
    restitution: float,
) -> tuple[float, float, float, float]:
    """Reflect the puck off the rails with restitution, and place it back inside.

    The velocity check matters: without it a puck resting against a wall would be flipped
    every tick and vibrate.
    """
    if x - puck_r <= bounds.x_min and vx < 0.0:
        vx = -vx * restitution
        x = bounds.x_min + puck_r
    elif x + puck_r >= bounds.x_max and vx > 0.0:
        vx = -vx * restitution
        x = bounds.x_max - puck_r

    if y - puck_r <= bounds.y_min and vy < 0.0:
        vy = -vy * restitution
        y = bounds.y_min + puck_r
    elif y + puck_r >= bounds.y_max and vy > 0.0:
        vy = -vy * restitution
        y = bounds.y_max - puck_r

    return x, y, vx, vy


def collide_puck_with_mallet(
    px: float,
    py: float,
    pvx: float,
    pvy: float,
    mx: float,
    my: float,
    mvx: float,
    mvy: float,
    puck_r: float,
    mallet_r: float,
    restitution: float,
) -> tuple[float, float, float, float]:
    """Resolve a puck/mallet overlap, returning the puck's position and velocity.

    The impulse acts along the line of centres and only when the puck is closing on the
    mallet, so a puck moving away is left alone. The puck is also pushed clear of the
    mallet on the same normal; without that separation a puck that stays in contact gets
    a second impulse on the next tick and gains energy it should not have.
    """
    dx = px - mx
    dy = py - my
    dist2 = dx * dx + dy * dy
    r_sum = puck_r + mallet_r

    if dist2 > r_sum * r_sum:
        return px, py, pvx, pvy

    if dist2 > 1e-12:
        dist = math.sqrt(dist2)
    else:
        # Exactly concentric: pick an arbitrary normal rather than divide by zero.
        dist = 0.0
        dx, dy = r_sum, 0.0

    if dist > 0.0:
        nx = dx / dist
        ny = dy / dist
    else:
        nx = 1.0
        ny = 0.0

    pv_n = pvx * nx + pvy * ny
    mv_n = mvx * nx + mvy * ny

    if pv_n - mv_n >= 0.0:
        # Separating already, so no impulse, but still push it clear if it overlaps.
        return _separate(px, py, mx, my, nx, ny, r_sum, pvx, pvy)

    rel = pv_n - mv_n
    pv_n_new = mv_n - restitution * rel

    pvx = pvx + (pv_n_new - pv_n) * nx
    pvy = pvy + (pv_n_new - pv_n) * ny

    return _separate(px, py, mx, my, nx, ny, r_sum, pvx, pvy)


def _separate(
    px: float,
    py: float,
    mx: float,
    my: float,
    nx: float,
    ny: float,
    r_sum: float,
    pvx: float,
    pvy: float,
) -> tuple[float, float, float, float]:
    px = mx + nx * (r_sum + 1e-4)
    py = my + ny * (r_sum + 1e-4)
    return px, py, pvx, pvy


def limit_mallet_velocity(
    mvx: float,
    mvy: float,
    cmd_vx: float,
    cmd_vy: float,
    a_max: float,
    dt: float,
    v_max: float,
) -> tuple[float, float]:
    """Move the mallet velocity toward the commanded velocity, limited by accel and speed."""
    dvx = cmd_vx - mvx
    dvy = cmd_vy - mvy
    dv = math.sqrt(dvx * dvx + dvy * dvy)

    if dv > a_max * dt and dv > 1e-12:
        s = (a_max * dt) / dv
        dvx *= s
        dvy *= s

    mvx += dvx
    mvy += dvy

    sp = math.sqrt(mvx * mvx + mvy * mvy)
    if sp > v_max and sp > 1e-12:
        scale = v_max / sp
        mvx *= scale
        mvy *= scale

    return mvx, mvy
