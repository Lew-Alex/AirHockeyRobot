"""Layer 1, world: the two mallets, the puck, and the fixed step that ties them together."""
from __future__ import annotations

import math
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from arena import Arena, INCH_M                                     # noqa: E402
from world import (EVENT_GOAL_FAR, EVENT_GOAL_NEAR, EVENT_MALLET,   # noqa: E402
                   EVENT_NONE, EVENT_RAIL, World, make_world)

DT = 1.0 / 1000.0


class TestSetup(unittest.TestCase):
    def test_default_world_has_two_mallets_and_a_puck(self):
        w = make_world()
        self.assertEqual(len(w.mallets), 2)
        self.assertEqual(w.arena.length_in, 48.0)
        self.assertEqual(w.arena.width_in, 24.0)
        self.assertAlmostEqual(w.puck.x, w.arena.length_m / 2.0, places=9)
        self.assertAlmostEqual(w.puck.y, w.arena.centre_y, places=9)

    def test_mallets_start_on_their_goal_lines(self):
        w = make_world()
        self.assertAlmostEqual(w.mallets[0].y, w.arena.centre_y, places=9)
        self.assertAlmostEqual(w.mallets[1].y, w.arena.centre_y, places=9)
        self.assertLess(w.mallets[0].x, w.mallets[1].x)

    def test_observation_is_the_full_state(self):
        w = make_world()
        obs = w.observation()
        self.assertEqual(obs.shape, (4 + 4 * 2,))
        self.assertTrue(np.all(np.isfinite(obs)))
        self.assertAlmostEqual(obs[0], w.puck.x, places=9)
        self.assertAlmostEqual(obs[4], w.mallets[0].x, places=9)
        self.assertAlmostEqual(obs[8], w.mallets[1].x, places=9)


class TestTwoMallets(unittest.TestCase):
    def test_the_undriven_mallet_does_not_move(self):
        w = make_world()
        for _ in range(2000):
            w.set_force(0, 200.0, -50.0)          # drive mallet 0 only
            w.step()
        self.assertEqual(w.mallets[1].speed, 0.0)
        self.assertAlmostEqual(w.mallets[1].x, w.arena.length_m - 0.12, places=9)

    def test_both_can_be_driven_independently(self):
        w = make_world()
        for _ in range(500):
            w.set_force(0, 200.0, 0.0)
            w.set_force(1, -200.0, 0.0)
            w.step()
        self.assertGreater(w.mallets[0].x, 0.12)
        self.assertLess(w.mallets[1].x, w.arena.length_m - 0.12)

    def test_clearing_forces_leaves_them_coasting(self):
        w = make_world()
        for _ in range(200):
            w.set_force(0, 200.0, 0.0)
            w.step()
        speed_before = w.mallets[0].speed
        w.clear_forces()
        for _ in range(200):
            w.step()
        self.assertAlmostEqual(w.mallets[0].speed, speed_before, places=9)


class TestStepping(unittest.TestCase):
    def test_time_and_step_count_advance_together(self):
        w = make_world()
        for _ in range(50):
            w.step()
        self.assertAlmostEqual(w.t, 50 * DT, places=9)
        self.assertEqual(w.n_steps, 50)

    def test_step_many_reports_the_most_significant_event(self):
        w = make_world()
        w.mallets[1].teleport(w.arena.length_m - 0.15, 0.05)   # off the puck's line
        w.puck.launch(w.arena.length_m - 0.2, w.arena.centre_y, 3.0, 0.0)
        event = w.step_many(4000)
        self.assertEqual(event, EVENT_GOAL_FAR)

    def test_a_goal_at_the_near_end(self):
        w = make_world()
        w.mallets[0].teleport(0.9, 0.05)                    # out of the way
        w.puck.launch(0.4, w.arena.centre_y, -4.0, 0.0)
        event = w.step_many(4000)
        self.assertEqual(event, EVENT_GOAL_NEAR)

    def test_a_driven_mallet_can_hit_the_puck(self):
        w = make_world()
        w.puck.launch(0.5, w.arena.centre_y, 0.0, 0.0)
        w.mallets[0].teleport(0.2, w.arena.centre_y)
        seen = EVENT_NONE
        for _ in range(2000):
            w.set_force(0, 300.0, 0.0)
            event = w.step()
            if event == EVENT_MALLET:
                seen = event
                break
        self.assertEqual(seen, EVENT_MALLET)
        self.assertIsNotNone(w.last_contact)
        self.assertGreater(w.puck.speed, 1.0)

    def test_a_rail_bounce_is_reported(self):
        w = make_world()
        w.puck.launch(0.6, w.arena.width_m - 0.04, 0.0, 5.0)
        self.assertEqual(w.step_many(200), EVENT_RAIL)

    def test_reset_placement_puts_everything_back(self):
        w = make_world()
        w.puck.launch(0.9, 0.5, 6.0, -3.0)
        w.mallets[0].teleport(0.9, 0.5)
        w.reset_placement()
        self.assertAlmostEqual(w.puck.speed, 0.0)
        self.assertAlmostEqual(w.puck.x, w.arena.length_m / 2.0, places=9)
        self.assertAlmostEqual(w.mallets[0].x, 0.12, places=9)
        self.assertEqual(w.t, 0.0)

    def test_determinism(self):
        def run_once():
            w = make_world()
            w.puck.launch(0.9, 0.3, 5.0, 0.4)
            for _ in range(600):
                w.set_force(0, 220.0, -40.0)
                w.step()
            return w.observation()

        np.testing.assert_array_equal(run_once(), run_once())

    def test_a_long_run_stays_finite_and_inside(self):
        w = make_world()
        w.puck.launch(0.9, 0.3, 6.0, 1.0)
        for i in range(30000):
            w.set_force(0, 300.0 * math.sin(i / 90.0), 300.0 * math.cos(i / 130.0))
            w.step()
            if w.event in (EVENT_GOAL_NEAR, EVENT_GOAL_FAR):
                w.reset_placement()
                w.puck.launch(0.9, 0.3, 6.0, 0.5)
            self.assertTrue(np.all(np.isfinite(w.observation())))
            self.assertTrue(w.arena.contains(w.puck.x, w.puck.y, w.puck.radius - 1e-6)
                            or w.arena.in_goal_mouth(w.puck.y))

    def test_the_puck_crosses_the_table_in_the_expected_time(self):
        """48 inches at 5 m/s: the puck should cover it in about length / speed, less the
        small drag loss. Both mallets are parked off the puck's line so nothing blocks it."""
        w = make_world()
        w.mallets[0].teleport(0.1, 0.05)
        w.mallets[1].teleport(w.arena.length_m - 0.1, 0.05)
        w.puck.launch(0.05, w.arena.centre_y, 5.0, 0.0)
        for _ in range(4000):
            w.step()
            if w.event == EVENT_GOAL_FAR:
                break
        expected = (w.arena.length_m - 0.05) / 5.0
        self.assertEqual(w.event, EVENT_GOAL_FAR)
        self.assertAlmostEqual(w.t, expected, delta=0.06)


class TestArenaDefaults(unittest.TestCase):
    def test_the_arena_is_the_size_asked_for(self):
        a = Arena()
        self.assertAlmostEqual(a.length_m, 48 * INCH_M, places=9)
        self.assertAlmostEqual(a.width_m, 24 * INCH_M, places=9)

    def test_world_accepts_a_custom_arena(self):
        w = World(arena=Arena(length_in=24.0, width_in=12.0))
        w.reset_placement()
        self.assertAlmostEqual(w.arena.length_m, 24 * INCH_M, places=9)


if __name__ == "__main__":
    unittest.main(verbosity=2)
