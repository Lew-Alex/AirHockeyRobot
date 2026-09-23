"""Layer 1: the puck.

The puck carries its own physics:

  * translation with linear drag plus a small Coulomb (sliding) term
  * bounces off the arena rails, with the arena owning the geometry
  * collisions with a mallet, using restitution and the mallet's mass

Nothing else in the simulator models the puck's behaviour, so the puck is the one place to
look when the puck does something wrong.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from arena import Arena


@dataclass
class Contact:
    """Record of a puck to mallet contact, kept so the impulse can be checked."""

    t_hit: float
    normal: tuple[float, float]
    v_mallet_normal: float
    v_puck_normal_before: float
    v_puck_normal_after: float
    gap_m: float


def collision_exit_speed(v_mallet_n: float, v_puck_n: float, m_puck: float,
                         m_mallet: float, restitution: float) -> float:
    """Post-collision puck speed along the contact normal.

    One dimensional collision with restitution e, mallet mass M, puck mass m:
        v_p' = [ M (1 + e) v_m + (m - e M) v_p ] / (M + m)
    In the limit M >> m this reduces to v_p' = v_m (1 + e) + e v_p, the form quoted in the
    project notes.
    """
    return (m_mallet * (1.0 + restitution) * v_mallet_n
            + (m_puck - restitution * m_mallet) * v_puck_n) / (m_mallet + m_puck)


class Puck:
    """A round puck on the air cushion.

    Geometry and inertia are constructor arguments so the same class covers a 20 g
    practice puck and a heavier league puck.
    """

    def __init__(self, x: float = 0.0, y: float = 0.0, vx: float = 0.0, vy: float = 0.0,
                 radius_m: float = 0.03175, mass_kg: float = 0.022,
                 drag_per_s: float = 0.08, coulomb_mu: float = 0.002,
                 max_speed_m_s: float = 40.0):
        self.x, self.y, self.vx, self.vy = x, y, vx, vy
        self.radius = self.radius_m = radius_m
        self.mass_kg = mass_kg
        self.drag_per_s = drag_per_s
        self.coulomb_mu = coulomb_mu
        self.max_speed_m_s = max_speed_m_s

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

    def place(self, x: float, y: float) -> None:
        self.x, self.y = x, y

    def launch(self, x: float, y: float, vx: float, vy: float) -> None:
        self.x, self.y, self.vx, self.vy = x, y, vx, vy

    def stop(self) -> None:
        self.vx = self.vy = 0.0

    # ------------------------------------------------------------------ physics
    def integrate(self, dt: float) -> None:
        """Move the puck one step, applying drag.

        Drag is linear (air film) plus a small Coulomb term (contact friction). Both are
        small on a working air table, which is why a puck crosses the table with little
        loss and why a weak blower shows up as a wrong-looking glide.
        """
        speed = self.speed
        if speed > 1e-9:
            decel = self.drag_per_s * speed + self.coulomb_mu * 9.81
            scale = max(0.0, 1.0 - decel * dt / speed)
            self.vx *= scale
            self.vy *= scale
        self.x += self.vx * dt
        self.y += self.vy * dt

    def resolve_wall(self, arena: Arena) -> str:
        return arena.resolve_wall(self)

    def collide_with(self, mallet, dt: float) -> Contact | None:
        """Detect and resolve a mallet contact inside one step.

        Solved on a swept basis: |d0 + v_rel t| = r_sum for the first root in [0, dt],
        with the mallet's velocity taken as constant across the step. A discrete overlap
        test would let a fast puck tunnel straight through the mallet.

        The tangential component of the puck's velocity is untouched (a frictionless
        contact), which is what makes a glancing hit deflect rather than stop.
        """
        r_sum = self.radius + mallet.radius
        d0x = self.x - mallet.x
        d0y = self.y - mallet.y
        vrx = self.vx - mallet.vx
        vry = self.vy - mallet.vy

        a = vrx * vrx + vry * vry
        c = d0x * d0x + d0y * d0y - r_sum * r_sum

        t_hit = None
        if c <= 0.0:
            t_hit = 0.0                       # already overlapping, resolve now
        elif a > 1e-12:
            b = 2.0 * (d0x * vrx + d0y * vry)
            disc = b * b - 4.0 * a * c
            if disc >= 0.0:
                root = math.sqrt(disc)
                for t in ((-b - root) / (2.0 * a), (-b + root) / (2.0 * a)):
                    if 0.0 <= t <= dt:
                        t_hit = t
                        break
        if t_hit is None:
            return None

        cx = d0x + vrx * t_hit
        cy = d0y + vry * t_hit
        dist = math.hypot(cx, cy)
        nx, ny = (1.0, 0.0) if dist < 1e-12 else (cx / dist, cy / dist)

        # separate exactly to the contact distance
        self.x = mallet.x + nx * r_sum
        self.y = mallet.y + ny * r_sum

        v_p_n = self.vx * nx + self.vy * ny
        v_m_n = mallet.vx * nx + mallet.vy * ny
        v_p_after = v_p_n

        if v_p_n < v_m_n:                     # the mallet is closing, so there is an impulse
            v_p_after = collision_exit_speed(v_m_n, v_p_n, self.mass_kg,
                                             mallet.effective_mass_kg, mallet.restitution)
            v_t_x = self.vx - v_p_n * nx
            v_t_y = self.vy - v_p_n * ny
            self.vx = v_p_after * nx + v_t_x
            self.vy = v_p_after * ny + v_t_y

        remaining = dt - t_hit
        if remaining > 0.0:
            self.x += self.vx * remaining
            self.y += self.vy * remaining

        if self.speed > self.max_speed_m_s:
            scale = self.max_speed_m_s / self.speed
            self.vx *= scale
            self.vy *= scale

        return Contact(t_hit=t_hit, normal=(nx, ny), v_mallet_normal=v_m_n,
                       v_puck_normal_before=v_p_n, v_puck_normal_after=v_p_after,
                       gap_m=r_sum)
