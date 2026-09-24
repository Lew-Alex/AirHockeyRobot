from __future__ import annotations

from dataclasses import dataclass


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def predict_crossing_time(defense_plane_y: float, py: float, vy: float, vy_epsilon: float) -> float | None:
    # Solve for time when y(t) = defense_plane_y with constant-velocity motion.
    if abs(vy) < vy_epsilon:
        return None
    t = (defense_plane_y - py) / vy
    if t <= 0.0:
        return None
    return float(t)


@dataclass(frozen=True)
class Target:
    x: float
    y: float


def compute_defense_target(
    *,
    px: float,
    py: float,
    vx: float,
    vy: float,
    defense_plane_y: float,
    x_min: float,
    x_max: float,
    y_min: float,
    y_max: float,
    margin: float,
    vy_epsilon: float,
) -> Target:
    t = predict_crossing_time(defense_plane_y, py, vy, vy_epsilon)

    if t is not None:
        tx = px + vx * t
        ty = defense_plane_y
    else:
        # Mirror fallback about the defense plane.
        tx = px
        ty = 2.0 * defense_plane_y - py

    tx = clamp(tx, x_min + margin, x_max - margin)
    ty = clamp(ty, y_min + margin, y_max - margin)

    return Target(x=float(tx), y=float(ty))
