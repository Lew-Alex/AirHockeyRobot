"""Layer 1, puck: drag, wall response, and the mallet collision."""
from __future__ import annotations

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from arena import Arena                                    # noqa: E402
from mallet import Mallet                                   # noqa: E402
from puck import Puck, collision_exit_speed                 # noqa: E402

DT = 1.0 / 1000.0


class TestCollisionModel(unittest.TestCase):
    def test_matches_the_infinite_mass_limit(self):
        v = collision_exit_speed(8.0, 0.0, 0.022, 1e6, 0.70)
        self.assertAlmostEqual(v, 8.0 * 1.70, places=3)

    def test_a_dead_puck_comes_out_at_one_point_seven_times_the_mallet(self):
        # with e = 0.7 and a mallet much heavier than the puck, v = v_m (1 + e)
        v = collision_exit_speed(10.0, 0.0, 0.022, 0.60, 0.70)
        self.assertAlmostEqual(v, 10.0 * 1.70 * (0.60 / 0.622), delta=0.05)

    def test_an_incoming_puck_needs_less_mallet_speed(self):
        v = collision_exit_speed(3.0, -12.0, 0.022, 0.60, 0.70)
        self.assertGreater(v, 3.0 * 1.70)


class TestPuckMotion(unittest.TestCase):
    def test_drag_only_slows_it(self):
        p = Puck(x=0.0, y=0.3, vx=8.0)
        speeds = []
        for _ in range(200):
            p.integrate(DT)
            speeds.append(p.speed)
        self.assertEqual(speeds, sorted(speeds, reverse=True))
        self.assertLess(1.0 - speeds[-1] / 8.0, 0.03)      # an air table is nearly frictionless
        self.assertGreater(1.0 - speeds[-1] / 8.0, 0.0)

    def test_straight_line_at_constant_speed_approx(self):
        p = Puck(x=0.2, y=0.3, vx=5.0)
        for _ in range(100):
            p.integrate(DT)
        self.assertAlmostEqual(p.x - 0.2, 5.0 * 0.1, delta=0.01)
        self.assertAlmostEqual(p.y, 0.3, places=9)

    def test_a_weak_blower_shows_up_as_a_wrong_glide(self):
        """The Coulomb term is the sliding friction, which is what a badly working blower
        would dominate. Over half a second it costs a few percent of the speed, so a puck
        that dies halfway across the table means the blower, not the linear drag."""
        fast = Puck(x=0.0, y=0.3, vx=8.0, coulomb_mu=0.0)
        sticky = Puck(x=0.0, y=0.3, vx=8.0, coulomb_mu=0.20)
        for _ in range(500):
            fast.integrate(DT)
            sticky.integrate(DT)
        self.assertLess(sticky.speed, fast.speed)
        self.assertGreater(1.0 - sticky.speed / fast.speed, 0.05)


class TestPuckMalletContact(unittest.TestCase):
    def setUp(self):
        self.arena = Arena()
        self.mallet = Mallet(x=0.6, y=0.3048)

    def test_head_on_contact_matches_the_closed_form(self):
        r_sum = 0.03175 + self.mallet.radius
        p = Puck(x=self.mallet.x - (r_sum + 0.002), y=0.3048, vx=4.0, vy=0.0)
        contact = p.collide_with(self.mallet, DT)
        self.assertIsNotNone(contact)
        assert contact is not None
        expected = collision_exit_speed(0.0, -4.0, p.mass_kg,
                                        self.mallet.effective_mass_kg, self.mallet.restitution)
        self.assertAlmostEqual(contact.v_puck_normal_after, expected, places=12)
        self.assertLess(p.vx, 0.0)                        # sent back the way it came

    def test_tangential_speed_is_untouched(self):
        """A frictionless contact leaves the velocity component perpendicular to the
        contact normal alone. The normal is not exactly the x axis here, because the puck
        drifts in y while it closes, so the check has to be done along the real normal."""
        r_sum = 0.03175 + self.mallet.radius
        v0 = (4.0, 2.0)
        p = Puck(x=self.mallet.x - (r_sum + 0.002), y=0.3048, vx=v0[0], vy=v0[1])
        contact = p.collide_with(self.mallet, DT)
        self.assertIsNotNone(contact)
        assert contact is not None
        nx, ny = contact.normal

        def tangential(v):
            vn = v[0] * nx + v[1] * ny
            return v[0] - vn * nx, v[1] - vn * ny

        before = tangential(v0)
        after = tangential((p.vx, p.vy))
        self.assertAlmostEqual(before[0], after[0], places=9)
        self.assertAlmostEqual(before[1], after[1], places=9)
        # and the normal component really did reverse
        self.assertGreater(contact.v_puck_normal_after, 0.0)
        self.assertLess(contact.v_puck_normal_before, 0.0)

    def test_separated_to_the_contact_distance(self):
        p = Puck(x=0.5, y=0.3048, vx=4.0)
        r_sum = p.radius + self.mallet.radius
        p.x = self.mallet.x - (r_sum + 0.002)
        p.collide_with(self.mallet, DT)
        gap = math.hypot(p.x - self.mallet.x, p.y - self.mallet.y)
        self.assertGreaterEqual(gap, r_sum - 1e-12)
        self.assertLessEqual(gap, r_sum + abs(p.vx) * DT + 1e-9)

    def test_a_fast_puck_cannot_pass_through_a_slow_step(self):
        """A 12 ms step at 30 m/s travels 360 mm and ends 334 mm past the mallet, so a
        discrete overlap test would see nothing. The swept solve must still catch it."""
        p = Puck(x=0.5, y=0.3048, vx=30.0)
        self.mallet.teleport(0.76, 0.3048)
        r_sum = p.radius + self.mallet.radius
        self.assertGreater(30.0 * 0.012, r_sum)
        self.assertGreater(abs((0.5 + 0.36) - 0.76), r_sum)
        contact = p.collide_with(self.mallet, 0.012)
        self.assertIsNotNone(contact)
        self.assertLess(p.vx, -15.0)

    def test_a_receding_mallet_does_not_launch_the_puck(self):
        p = Puck(x=0.5, y=0.3048, vx=0.0)
        self.mallet.teleport(0.5 + p.radius + self.mallet.radius + 0.002, 0.3048)
        self.mallet.set_velocity(2.0, 0.0)
        self.assertIsNone(p.collide_with(self.mallet, DT))
        self.assertLess(p.speed, 1e-9)

    def test_no_contact_when_passing_sideways(self):
        p = Puck(x=0.5, y=0.05, vx=5.0)
        self.assertIsNone(p.collide_with(self.mallet, DT))


class TestPuckWalls(unittest.TestCase):
    def test_puck_bounces_via_the_arena(self):
        arena = Arena()
        p = Puck(x=0.3, y=arena.width_m - 0.001, vx=1.0, vy=4.0)
        p.integrate(DT)
        event = p.resolve_wall(arena)
        self.assertEqual(event, "rail")
        self.assertLess(p.vy, 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
