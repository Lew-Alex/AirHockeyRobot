"""Layer 1: the world.

Holds the arena, one puck and two mallets, and advances them together on a fixed
timestep. The only thing the outside world can do to it is push a mallet with a force,
which is the interface the input layer uses.

Events, in the order they matter:
    goal_near / goal_far   the puck crossed a goal line inside the mouth
    mallet                 the puck touched a mallet this step
    rail                   the puck bounced off a rail
    none
"""
from __future__ import annotations

import math

import numpy as np

from arena import HIT_GOAL_FAR, HIT_GOAL_NEAR, HIT_NONE, HIT_RAIL, Arena
from mallet import Mallet
from puck import Puck

EVENT_NONE = "none"
EVENT_RAIL = "rail"
EVENT_MALLET = "mallet"
EVENT_GOAL_NEAR = "goal_near"
EVENT_GOAL_FAR = "goal_far"

EVENT_PRIORITY = {EVENT_NONE: 0, EVENT_RAIL: 1, EVENT_MALLET: 2,
                  EVENT_GOAL_NEAR: 3, EVENT_GOAL_FAR: 3}

DEFAULT_DT_S = 1.0 / 1000.0        # 1 kHz, matching the eventual control loop


class World:
    """Arena plus puck plus two mallets."""

    def __init__(self, arena: Arena | None = None, puck: Puck | None = None,
                 mallets: list[Mallet] | None = None, dt_s: float = DEFAULT_DT_S):
        self.arena = arena or Arena()
        self.puck = puck or Puck()
        self.mallets = mallets if mallets is not None else [
            Mallet(x=0.12, y=0.0),                       # near end, the one being driven
            Mallet(x=1.10, y=0.0),                       # far end, stationary for now
        ]
        self.dt_s = dt_s
        self.t = 0.0
        self.event = EVENT_NONE
        self.last_contact = None
        self.max_puck_speed = 0.0
        self.n_steps = 0
        self.forces = [(0.0, 0.0) for _ in self.mallets]
        self.reset_placement()

    # ------------------------------------------------------------------ setup
    def reset_placement(self, puck_at: tuple[float, float] | None = None,
                        puck_velocity: tuple[float, float] | None = None,
                        reset_clock: bool = True) -> None:
        """Put everything back on the table: puck at centre, mallets on their goal lines.

        `reset_clock=False` keeps the time and step counters running, which is what a game
        loop wants after a goal. Resetting the clock there is a trap: a loop that stops on
        `t >= seconds` would never stop if every goal zeroed the clock.
        """
        arena = self.arena
        px, py = puck_at if puck_at else (arena.length_m / 2.0, arena.centre_y)
        self.puck.place(px, py)
        self.puck.stop()
        if puck_velocity:
            self.puck.vx, self.puck.vy = puck_velocity
        for i, mallet in enumerate(self.mallets):
            side = 0.12 if i == 0 else arena.length_m - 0.12
            mallet.teleport(side, arena.centre_y)
            mallet.stop()
            mallet.force_x = mallet.force_y = 0.0
        if reset_clock:
            self.t = 0.0
            self.n_steps = 0
        self.event = EVENT_NONE
        self.last_contact = None
        self.max_puck_speed = self.puck.speed

    # ------------------------------------------------------------------ control
    def set_force(self, mallet_index: int, force_x: float, force_y: float) -> None:
        self.forces[mallet_index] = (force_x, force_y)

    def clear_forces(self) -> None:
        for i in range(len(self.mallets)):
            self.forces[i] = (0.0, 0.0)

    # ------------------------------------------------------------------ stepping
    def step(self, dt: float | None = None) -> str:
        """Advance everything by one timestep. Returns the step's event."""
        dt = self.dt_s if dt is None else dt
        arena, puck = self.arena, self.puck

        for i, mallet in enumerate(self.mallets):
            fx, fy = self.forces[i]
            mallet.apply_force(fx, fy, dt)
            mallet.keep_inside(arena)

        puck.integrate(dt)
        event = EVENT_NONE
        wall = puck.resolve_wall(arena)
        if wall == HIT_GOAL_NEAR:
            event = EVENT_GOAL_NEAR
        elif wall == HIT_GOAL_FAR:
            event = EVENT_GOAL_FAR
        elif wall == HIT_RAIL:
            event = EVENT_RAIL

        if event not in (EVENT_GOAL_NEAR, EVENT_GOAL_FAR):
            for mallet in self.mallets:
                contact = puck.collide_with(mallet, dt)
                if contact is not None:
                    self.last_contact = contact
                    event = EVENT_MALLET
                    wall = puck.resolve_wall(arena)
                    if wall == HIT_GOAL_NEAR:
                        event = EVENT_GOAL_NEAR
                    elif wall == HIT_GOAL_FAR:
                        event = EVENT_GOAL_FAR
                    break

        self.max_puck_speed = max(self.max_puck_speed, puck.speed)
        self.event = event
        self.t += dt
        self.n_steps += 1
        if not math.isfinite(puck.x + puck.y + self.mallets[0].x + self.mallets[1].x):
            raise FloatingPointError("state went non-finite")
        return event

    def step_many(self, n: int, dt: float | None = None) -> str:
        """Advance n timesteps, reporting the most significant event seen."""
        dt = self.dt_s if dt is None else dt
        best = EVENT_NONE
        for _ in range(n):
            event = self.step(dt)
            if EVENT_PRIORITY[event] > EVENT_PRIORITY[best]:
                best = event
            if event in (EVENT_GOAL_NEAR, EVENT_GOAL_FAR):
                break
        self.event = best
        return best

    # ------------------------------------------------------------------ readout
    def observation(self) -> np.ndarray:
        """Raw SI state: puck, then both mallets. Normalisation belongs to the caller."""
        parts = [self.puck.x, self.puck.y, self.puck.vx, self.puck.vy]
        for mallet in self.mallets:
            parts += [mallet.x, mallet.y, mallet.vx, mallet.vy]
        return np.array(parts, dtype=np.float64)

    def summary(self) -> dict:
        return {
            "t": self.t,
            "event": self.event,
            "puck_speed": self.puck.speed,
            "mallet_speeds": [m.speed for m in self.mallets],
            "belt_speeds": [m.belt_speeds for m in self.mallets],
            "max_puck_speed": self.max_puck_speed,
            "n_steps": self.n_steps,
        }


def make_world(**kwargs) -> World:
    """A world with sensible defaults: two mallets on their goal lines, puck at centre."""
    world = World(**kwargs)
    world.reset_placement()
    return world
