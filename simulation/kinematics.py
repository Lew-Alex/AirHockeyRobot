"""CoreXY kinematics. Pure functions, no state, so they are trivial to unit test.

Belt naming follows the convention in the layout note:

    v_A = vx + vy
    v_B = vx - vy

so a positive v_A moves the carriage along the +x+y diagonal and a positive v_B moves
it along +x-y. Both motors sit on the frame, so their own mass never enters the moving
mass of the carriage.

The two hard properties the rest of the simulator depends on:

  * a pure axis move costs one belt speed per unit of carriage speed
  * a pure diagonal move costs sqrt(2) belt speed per unit of carriage speed, so the
    reachable carriage speed in a diagonal direction is 1/sqrt(2) of the axis limit

Both are enforced here rather than in the physics module, because they are a property
of the transmission and not of the puck.
"""
from __future__ import annotations

import math

import numpy as np

SQRT2 = math.sqrt(2.0)


def carriage_to_belt(vx: float, vy: float) -> tuple[float, float]:
    """Cartesian carriage velocity to belt velocities, (vA, vB)."""
    return vx + vy, vx - vy


def belt_to_carriage(v_a: float, v_b: float) -> tuple[float, float]:
    """Belt velocities (vA, vB) to Cartesian carriage velocity."""
    return (v_a + v_b) / 2.0, (v_a - v_b) / 2.0


def clip_belt_vector(v_a: float, v_b: float, v_max: float) -> tuple[float, float]:
    """Clip a belt velocity pair to the per-belt limit.

    Clipping in belt space is what makes the direction dependence fall out for free:
    a diagonal request has both belts large, so it saturates earlier.
    """
    return (
        float(np.clip(v_a, -v_max, v_max)),
        float(np.clip(v_b, -v_max, v_max)),
    )


def limit_carriage_velocity(vx: float, vy: float, v_max_belt: float) -> tuple[float, float]:
    """Maximum reachable carriage velocity in the requested direction.

    Pure x: v_belt = v_car, so v_car <= v_max.
    Diagonal: v_belt = sqrt(2) * v_car, so v_car <= v_max / sqrt(2).
    """
    v_a, v_b = clip_belt_vector(*carriage_to_belt(vx, vy), v_max_belt)
    return belt_to_carriage(v_a, v_b)


def diagonal_speed_ratio() -> float:
    """Carriage speed on a pure diagonal as a fraction of the axis speed limit."""
    return 1.0 / SQRT2


def carriage_speed(vx: float, vy: float) -> float:
    return math.hypot(vx, vy)


def belt_speed(vx: float, vy: float) -> tuple[float, float]:
    """Belt speeds for a carriage velocity, as magnitudes."""
    v_a, v_b = carriage_to_belt(vx, vy)
    return abs(v_a), abs(v_b)


def time_to_travel(distance_m: float, v_max: float, a_max: float) -> float:
    """Minimum time to cover a distance from rest with a velocity and acceleration cap.

    Trapezoidal profile: accelerate to the cap, cruise, decelerate.
    """
    if distance_m <= 0.0:
        return 0.0
    d_accel = v_max * v_max / (2.0 * a_max)
    if distance_m <= 2.0 * d_accel:
        # triangular, never reaches the cap
        return 2.0 * math.sqrt(distance_m / a_max)
    return 2.0 * (v_max / a_max) + (distance_m - 2.0 * d_accel) / v_max


def reachable_distance(time_s: float, v_max: float, a_max: float) -> float:
    """Distance coverable from rest in a time, with both caps."""
    if time_s <= 0.0:
        return 0.0
    t_accel = v_max / a_max
    if time_s <= 2.0 * t_accel:
        half = time_s / 2.0
        return a_max * half * half
    return a_max * t_accel * t_accel + v_max * (time_s - 2.0 * t_accel)
