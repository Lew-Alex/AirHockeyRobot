"""Layer 1: the arena.

A rectangle of air hockey table with walls and a goal mouth at each end. The arena owns
geometry and the wall behaviour; it does not know about the puck or the mallets in any
detail beyond "something round with a radius is bouncing off me".

Units: the arena is defined in inches because that is how tables are sold, and everything
else in the simulator works in metres. The conversion lives here and nowhere else.
"""
from __future__ import annotations

from dataclasses import dataclass

INCH_M = 0.0254

# what the arena reports when something hits it
HIT_NONE = "none"
HIT_RAIL = "rail"
HIT_GOAL_NEAR = "goal_near"     # x = 0, the near end
HIT_GOAL_FAR = "goal_far"       # x = length, the far end


@dataclass
class Arena:
    """24 x 48 inches, which is a small home table.

    The x axis runs the long way (48 in) and y runs across (24 in). The near goal is at
    x = 0 and the far goal at x = length_m.

    Not frozen, because the parameter panel writes wall restitution and the goal width
    into a live arena. Geometry stays fixed: changing the table size mid-run would move
    the mallets out from under themselves.
    """

    length_in: float = 48.0
    width_in: float = 24.0
    goal_width_in: float = 12.0      # TODO(Alex): measure the real table
    wall_restitution: float = 0.90   # TODO(Alex): estimate, rails are not perfectly elastic

    @property
    def length_m(self) -> float:
        return self.length_in * INCH_M

    @property
    def width_m(self) -> float:
        return self.width_in * INCH_M

    @property
    def goal_width_m(self) -> float:
        return self.goal_width_in * INCH_M

    @property
    def centre_y(self) -> float:
        return self.width_m / 2.0

    # ------------------------------------------------------------------ geometry
    def contains(self, x: float, y: float, radius: float = 0.0) -> bool:
        return (radius <= x <= self.length_m - radius
                and radius <= y <= self.width_m - radius)

    def clamp(self, x: float, y: float, radius: float = 0.0) -> tuple[float, float]:
        """Keep a centre inside the arena, allowing for its own radius."""
        return (
            min(max(x, radius), self.length_m - radius),
            min(max(y, radius), self.width_m - radius),
        )

    def in_goal_mouth(self, y: float) -> bool:
        return abs(y - self.centre_y) <= self.goal_width_m / 2.0

    def goal_span_m(self) -> tuple[float, float]:
        half = self.goal_width_m / 2.0
        return self.centre_y - half, self.centre_y + half

    def pixel_to_metres(self, px: float, py: float, origin_px: tuple[float, float],
                        scale_px_per_m: float) -> tuple[float, float]:
        """Screen pixels to arena coordinates, for the input layer."""
        return (px - origin_px[0]) / scale_px_per_m, (py - origin_px[1]) / scale_px_per_m

    # ------------------------------------------------------------------ walls
    def resolve_wall(self, body) -> str:
        """Bounce a round body off the rails, or report a goal.

        `body` needs x, y, vx, vy and radius. Returns one of HIT_*.
        """
        r = body.radius

        if body.x - r < 0.0:
            if self.in_goal_mouth(body.y):
                return HIT_GOAL_NEAR
            body.x = r
            body.vx = -body.vx * self.wall_restitution
            return HIT_RAIL

        if body.x + r > self.length_m:
            if self.in_goal_mouth(body.y):
                return HIT_GOAL_FAR
            body.x = self.length_m - r
            body.vx = -body.vx * self.wall_restitution
            return HIT_RAIL

        if body.y - r < 0.0:
            body.y = r
            body.vy = -body.vy * self.wall_restitution
            return HIT_RAIL

        if body.y + r > self.width_m:
            body.y = self.width_m - r
            body.vy = -body.vy * self.wall_restitution
            return HIT_RAIL

        return HIT_NONE
