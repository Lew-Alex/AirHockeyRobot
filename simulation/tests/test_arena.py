"""Layer 1, arena: geometry and wall behaviour."""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from arena import HIT_GOAL_FAR, HIT_GOAL_NEAR, HIT_NONE, HIT_RAIL, Arena  # noqa: E402
from puck import Puck  # noqa: E402


class TestArenaGeometry(unittest.TestCase):
    def test_inches_to_metres(self):
        a = Arena(length_in=48.0, width_in=24.0)
        self.assertAlmostEqual(a.length_m, 1.2192, places=9)
        self.assertAlmostEqual(a.width_m, 0.6096, places=9)

    def test_goal_span_is_centred(self):
        a = Arena(goal_width_in=12.0)
        lo, hi = a.goal_span_m()
        self.assertAlmostEqual((lo + hi) / 2.0, a.width_m / 2.0, places=9)
        self.assertAlmostEqual(hi - lo, 12.0 * 0.0254, places=9)

    def test_contains_and_clamp_respect_a_radius(self):
        a = Arena()
        r = 0.05
        self.assertTrue(a.contains(0.5, 0.3, r))
        self.assertFalse(a.contains(0.02, 0.3, r))       # too close to the near wall
        x, y = a.clamp(-1.0, 99.0, r)
        self.assertAlmostEqual(x, r, places=9)
        self.assertAlmostEqual(y, a.width_m - r, places=9)

    def test_in_goal_mouth(self):
        a = Arena(goal_width_in=12.0)
        self.assertTrue(a.in_goal_mouth(a.centre_y))
        self.assertFalse(a.in_goal_mouth(a.centre_y + a.goal_width_m))


class TestArenaWalls(unittest.TestCase):
    def setUp(self):
        self.a = Arena()
        self.puck = Puck(radius_m=0.03175, mass_kg=0.022)

    def test_side_wall_bounces_and_keeps_the_tangential_speed(self):
        p = self.puck
        p.launch(0.5, 0.01, 2.0, -3.0)         # inside the wall by more than its radius
        hit = self.a.resolve_wall(p)
        self.assertEqual(hit, HIT_RAIL)
        self.assertAlmostEqual(p.vy, 3.0 * self.a.wall_restitution, places=9)
        self.assertAlmostEqual(p.vx, 2.0, places=9)

    def test_near_goal_is_a_goal_not_a_bounce(self):
        p = self.puck
        p.launch(p.radius - 0.001, self.a.centre_y, -3.0, 0.0)
        self.assertEqual(self.a.resolve_wall(p), HIT_GOAL_NEAR)

    def test_far_goal_is_a_goal(self):
        p = self.puck
        p.launch(self.a.length_m - p.radius + 0.001, self.a.centre_y, 3.0, 0.0)
        self.assertEqual(self.a.resolve_wall(p), HIT_GOAL_FAR)

    def test_end_wall_outside_the_mouth_bounces(self):
        p = self.puck
        p.launch(p.radius - 0.001, 0.05, -3.0, 0.0)
        self.assertEqual(self.a.resolve_wall(p), HIT_RAIL)
        self.assertGreater(p.vx, 0.0)

    def test_nothing_happens_in_open_play(self):
        p = self.puck
        p.launch(0.5, 0.3, 1.0, 1.0)
        self.assertEqual(self.a.resolve_wall(p), HIT_NONE)


if __name__ == "__main__":
    unittest.main(verbosity=2)
