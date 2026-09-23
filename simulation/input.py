"""Layer 2: the inputs.

Layer 1 knows nothing about mice, keyboards or screens. It accepts a force on a mallet
and nothing else. This layer turns a mouse position into that force.

The chain is:

    mouse pixels  ->  arena coordinates  ->  force  ->  world.set_force(0, fx, fy)

Only mallet 0 has an input. Mallet 1 receives no force at all and therefore stays where
it is, which is the "two mallets, one driven" arrangement for now.

The force is a proportional plus derivative (PD) push toward the pointer: a spring that
pulls the mallet to the cursor, with damping so it does not oscillate around the target.
The stiffness, damping and force ceiling are all constructor arguments, so a policy or a
test can drive the same mallet without a mouse.
"""
from __future__ import annotations

import math

from mallet import Mallet
from world import World


class ForceController:
    """Target point to mallet force. The one piece of control logic in layer 2."""

    def __init__(self, mallet_index: int = 0, stiffness_n_per_m: float = 400.0,
                 damping_n_per_m_s: float = 40.0, max_force_n: float = 400.0,
                 dead_zone_m: float = 0.002):
        self.mallet_index = mallet_index
        self.stiffness_n_per_m = stiffness_n_per_m
        self.damping_n_per_m_s = damping_n_per_m_s
        self.max_force_n = max_force_n
        self.dead_zone_m = dead_zone_m
        self.target: tuple[float, float] | None = None
        self.last_force = (0.0, 0.0)

    def force(self, mallet: Mallet, target_xy: tuple[float, float]) -> tuple[float, float]:
        """A push toward the target, damped, and capped in magnitude."""
        self.target = target_xy
        ex = target_xy[0] - mallet.x
        ey = target_xy[1] - mallet.y
        if math.hypot(ex, ey) < self.dead_zone_m:
            # in the dead zone: only brake, do not pull
            fx = -self.damping_n_per_m_s * mallet.vx
            fy = -self.damping_n_per_m_s * mallet.vy
        else:
            fx = self.stiffness_n_per_m * ex - self.damping_n_per_m_s * mallet.vx
            fy = self.stiffness_n_per_m * ey - self.damping_n_per_m_s * mallet.vy
        magnitude = math.hypot(fx, fy)
        if magnitude > self.max_force_n > 0.0:
            scale = self.max_force_n / magnitude
            fx, fy = fx * scale, fy * scale
        self.last_force = (fx, fy)
        return fx, fy

    def apply(self, world: World, target_xy: tuple[float, float]) -> tuple[float, float]:
        """Write the force into the world for this controller's mallet."""
        mallet = world.mallets[self.mallet_index]
        fx, fy = self.force(mallet, target_xy)
        world.set_force(self.mallet_index, fx, fy)
        return fx, fy


class MouseInput:
    """Mouse pixels to arena coordinates, using the same layout the view draws with.

    `layout` is a view.Layout (it owns the pixel origin and scale) so the cursor lands
    where it looks like it lands. Anything with `origin_px` and `px_per_m` works.
    """

    def __init__(self, layout, controller: ForceController | None = None):
        self.layout = layout
        self.controller = controller or ForceController()
        self.mouse_px: tuple[float, float] | None = None
        self.target_m: tuple[float, float] | None = None

    def update_pointer(self, mouse_px: tuple[float, float]) -> tuple[float, float]:
        """Feed in the current cursor position and get back the arena target."""
        self.mouse_px = mouse_px
        x, y = self.layout.pixel_to_metres(*mouse_px)
        self.target_m = (x, y)
        return self.target_m

    def force(self, world: World) -> tuple[float, float]:
        if self.target_m is None:
            return 0.0, 0.0
        target = world.arena.clamp(*self.target_m, world.mallets[self.controller.mallet_index].radius)
        return self.controller.force(world.mallets[self.controller.mallet_index], target)

    def apply(self, world: World) -> tuple[float, float]:
        mallet = world.mallets[self.controller.mallet_index]
        if self.target_m is None:
            world.set_force(self.controller.mallet_index, 0.0, 0.0)
            return 0.0, 0.0
        target = world.arena.clamp(*self.target_m, mallet.radius)
        return self.controller.apply(world, target)


class ScriptedInput:
    """A stand-in for the mouse: a target point that a test or a demo can set.

    Same interface as MouseInput where it matters, so headless runs exercise the same
    path the mouse does.
    """

    def __init__(self, target_m: tuple[float, float] = (0.5, 0.3),
                 controller: ForceController | None = None):
        self.controller = controller or ForceController()
        self.target_m = target_m

    def aim_at(self, x: float, y: float) -> None:
        self.target_m = (x, y)

    def aim_at_puck(self, world: World) -> None:
        self.target_m = (world.puck.x, world.puck.y)

    def apply(self, world: World) -> tuple[float, float]:
        return self.controller.apply(world, self.target_m)
