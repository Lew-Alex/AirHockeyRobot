"""Layer 1, mallet: force input, the stationary default, and the speed limits.

The two limits quoted for this build are 10 m/s along an axis and 7 m/s on a diagonal.
Both must fall out of one per-belt cap of 10 m/s, because that is the real constraint on a
CoreXY: each belt has a maximum speed and a diagonal move uses both belts at once.
"""
from __future__ import annotations

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from arena import Arena                                              # noqa: E402
from mallet import (BELT_SPEED_LIMIT_M_S, DIAGONAL_SPEED_LIMIT_M_S,   # noqa: E402
                    AXIAL_SPEED_LIMIT_M_S, Mallet)

DT = 1.0 / 1000.0


class TestStationaryByDefault(unittest.TestCase):
    def test_no_force_means_no_motion(self):
        m = Mallet(x=0.2, y=0.3)
        for _ in range(500):
            m.apply_force(0.0, 0.0, DT)
        self.assertAlmostEqual(m.x, 0.2, places=12)
        self.assertAlmostEqual(m.y, 0.3, places=12)
        self.assertEqual(m.speed, 0.0)

    def test_it_glides_when_pushed_then_released(self):
        """No rail friction in layer 1: the caps are the model, so a released mallet
        keeps its velocity. Layer 2 supplies the braking force."""
        m = Mallet()
        for _ in range(100):
            m.apply_force(100.0, 0.0, DT)
        v_after_push = m.vx
        for _ in range(100):
            m.apply_force(0.0, 0.0, DT)
        self.assertAlmostEqual(m.vx, v_after_push, places=9)


class TestForceResponse(unittest.TestCase):
    def test_force_accelerates_over_the_driven_mass(self):
        m = Mallet(mass_kg=0.60)
        m.apply_force(60.0, 0.0, DT)
        self.assertAlmostEqual(m.vx, 100.0 * DT, places=9)     # a = F / m = 100 m/s2

    def test_force_direction_sets_the_direction(self):
        m = Mallet()
        m.apply_force(0.0, 120.0, DT)
        self.assertGreater(m.vy, 0.0)
        self.assertAlmostEqual(m.vx, 0.0, places=12)

    def test_a_push_does_not_teleport(self):
        m = Mallet()
        m.apply_force(1000.0, 0.0, DT)
        self.assertLess(m.x, 100.0 * DT + 1e-9)


class TestSpeedLimits(unittest.TestCase):
    def _drive(self, m, fx, fy, steps=4000):
        for _ in range(steps):
            m.apply_force(fx, fy, DT)

    def test_axis_limit_is_ten_metres_per_second(self):
        m = Mallet()
        self._drive(m, 400.0, 0.0)
        self.assertAlmostEqual(m.vx, AXIAL_SPEED_LIMIT_M_S, places=9)
        self.assertAlmostEqual(m.speed, 10.0, places=9)

    def test_diagonal_limit_is_seven_metres_per_second(self):
        m = Mallet()
        # equal force on both axes: a 45 degree push
        self._drive(m, 400.0, 400.0)
        self.assertAlmostEqual(m.speed, DIAGONAL_SPEED_LIMIT_M_S, places=9)
        self.assertAlmostEqual(m.speed, 10.0 / math.sqrt(2.0), places=9)
        self.assertLess(m.speed, AXIAL_SPEED_LIMIT_M_S)

    def test_belt_cap_is_never_exceeded_in_any_direction(self):
        for angle_deg in range(0, 91, 15):
            m = Mallet()
            theta = math.radians(angle_deg)
            self._drive(m, 400.0 * math.cos(theta), 400.0 * math.sin(theta), steps=1500)
            for belt in m.belt_speeds:
                self.assertLessEqual(belt, BELT_SPEED_LIMIT_M_S + 1e-9)

    def test_a_pure_y_push_also_reaches_ten(self):
        m = Mallet()
        self._drive(m, 0.0, 400.0)
        self.assertAlmostEqual(m.speed, AXIAL_SPEED_LIMIT_M_S, places=9)


class TestStaysOnTheTable(unittest.TestCase):
    def test_a_hard_push_cannot_leave_the_arena(self):
        arena = Arena()
        m = Mallet(x=0.1, y=0.1)
        for _ in range(4000):
            m.apply_force(-4000.0, -4000.0, DT)
            m.keep_inside(arena)
        self.assertGreaterEqual(m.x, m.radius - 1e-9)
        self.assertGreaterEqual(m.y, m.radius - 1e-9)

    def test_the_far_corner_too(self):
        arena = Arena()
        m = Mallet(x=0.5, y=0.3)
        for _ in range(4000):
            m.apply_force(4000.0, 4000.0, DT)
            m.keep_inside(arena)
        self.assertLessEqual(m.x, arena.length_m - m.radius + 1e-9)
        self.assertLessEqual(m.y, arena.width_m - m.radius + 1e-9)


if __name__ == "__main__":
    unittest.main(verbosity=2)
