"""Layer 1: the mallet.

A mallet is a round body on the table that moves when you push it. The only control input
is a force in a direction, which is what the second layer produces. With no force it stays
put, which is why the second mallet in the world sits still until something drives it.

The speed limit is per belt, not per axis, because the machine is a CoreXY: both motors
are on the frame and each drives one belt. With a 10 m/s belt cap:

  * along an axis, v_belt = v_carriage, so the mallet reaches 10 m/s
  * on a pure diagonal, v_belt = sqrt(2) * v_carriage, so the mallet reaches 7.07 m/s

Those are the two numbers quoted for this build (10 m/s axial, 7 m/s diagonal), and they
fall out of the single belt cap rather than being enforced separately.
"""
from __future__ import annotations

import math

from kinematics import belt_to_carriage, carriage_to_belt, clip_belt_vector

BELT_SPEED_LIMIT_M_S = 10.0        # per belt. Gives 10 m/s axial, 7.07 m/s diagonal

AXIAL_SPEED_LIMIT_M_S = BELT_SPEED_LIMIT_M_S
DIAGONAL_SPEED_LIMIT_M_S = BELT_SPEED_LIMIT_M_S / math.sqrt(2.0)


class Mallet:
    """A mallet, driven by a force.

    `mass_kg` is the mass a force has to accelerate: the plastic mallet plus its share of
    the carriage and belt, not the bare mallet. A plastic mallet alone is about 0.12 kg,
    and the driven mass in the sizing study was 0.60 kg. The same figure is used for the
    impulse on the puck, so there is only one mass to reason about.
    """

    def __init__(self, x: float = 0.0, y: float = 0.0, vx: float = 0.0, vy: float = 0.0,
                 radius_m: float = 0.04125, mass_kg: float = 0.60,
                 restitution: float = 0.70,
                 belt_speed_limit_m_s: float = BELT_SPEED_LIMIT_M_S):
        self.x, self.y, self.vx, self.vy = x, y, vx, vy
        self.radius = self.radius_m = radius_m
        self.mass_kg = mass_kg
        self.effective_mass_kg = mass_kg        # used by the puck's collision model
        self.restitution = restitution
        self.belt_speed_limit_m_s = belt_speed_limit_m_s
        self.force_x = 0.0                      # the control input lives here
        self.force_y = 0.0

    # ------------------------------------------------------------------ state
    @property
    def speed(self) -> float:
        return math.hypot(self.vx, self.vy)

    @property
    def position(self) -> tuple[float, float]:
        return self.x, self.y

    @property
    def velocity(self) -> tuple[float, float]:
        return self.vx, self.vy

    @property
    def force(self) -> tuple[float, float]:
        return self.force_x, self.force_y

    @property
    def axial_speed_limit_m_s(self) -> float:
        return self.belt_speed_limit_m_s

    @property
    def diagonal_speed_limit_m_s(self) -> float:
        return self.belt_speed_limit_m_s / math.sqrt(2.0)

    @property
    def belt_speeds(self) -> tuple[float, float]:
        """Belt speeds as magnitudes, for checking the limit is respected."""
        v_a, v_b = carriage_to_belt(self.vx, self.vy)
        return abs(v_a), abs(v_b)

    def set_velocity(self, vx: float, vy: float) -> None:
        self.vx, self.vy = vx, vy
        self.clip_velocity()

    def teleport(self, x: float, y: float) -> None:
        self.x, self.y = x, y

    def stop(self) -> None:
        self.vx = self.vy = 0.0

    # ------------------------------------------------------------------ drive
    def apply_force(self, force_x: float, force_y: float, dt: float) -> None:
        """Push the mallet for one step, then enforce the belt speed limit."""
        self.force_x, self.force_y = force_x, force_y
        if dt <= 0.0:
            return
        self.vx += force_x / self.mass_kg * dt
        self.vy += force_y / self.mass_kg * dt
        self.clip_velocity()
        self.x += self.vx * dt
        self.y += self.vy * dt

    def clip_velocity(self) -> None:
        """Clip in belt space, which is what makes the diagonal limit fall out."""
        v_a, v_b = carriage_to_belt(self.vx, self.vy)
        v_a, v_b = clip_belt_vector(v_a, v_b, self.belt_speed_limit_m_s)
        self.vx, self.vy = belt_to_carriage(v_a, v_b)

    def keep_inside(self, arena) -> None:
        """Mallets are not allowed off the table, whatever the force says."""
        x, y = arena.clamp(self.x, self.y, self.radius)
        if x != self.x:
            self.x, self.vx = x, 0.0
        if y != self.y:
            self.y, self.vy = y, 0.0
