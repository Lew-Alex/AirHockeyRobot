"""Layer 2, inputs: mouse pixels to a force on one mallet, with an equivalent for tests."""
from __future__ import annotations

import math
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from input import ForceController, MouseInput, ScriptedInput     # noqa: E402
from view import Layout                                          # noqa: E402
from world import World, make_world                              # noqa: E402


class TestForceController(unittest.TestCase):
    def test_it_pushes_toward_the_target(self):
        w = make_world()
        c = ForceController(mallet_index=0)
        m = w.mallets[0]
        fx, fy = c.force(m, (m.x + 0.2, m.y + 0.1))
        self.assertGreater(fx, 0.0)
        self.assertGreater(fy, 0.0)

    def test_it_brakes_when_already_at_the_target(self):
        w = make_world()
        c = ForceController()
        m = w.mallets[0]
        m.set_velocity(2.0, -1.0)
        fx, fy = c.force(m, (m.x, m.y))
        self.assertLess(fx, 0.0)
        self.assertGreater(fy, 0.0)

    def test_the_force_is_capped(self):
        w = make_world()
        c = ForceController(stiffness_n_per_m=5000.0, max_force_n=250.0)
        fx, fy = c.force(w.mallets[0], (50.0, 50.0))
        self.assertAlmostEqual(math.hypot(fx, fy), 250.0, places=6)

    def test_the_dead_zone_does_not_pull(self):
        w = make_world()
        c = ForceController(dead_zone_m=0.01)
        m = w.mallets[0]
        fx, fy = c.force(m, (m.x + 0.001, m.y))
        self.assertAlmostEqual(fx, 0.0, places=9)
        self.assertAlmostEqual(fy, 0.0, places=9)

    def test_apply_writes_the_force_into_the_world(self):
        w = make_world()
        c = ForceController(mallet_index=0, damping_n_per_m_s=0.0)
        c.apply(w, (w.mallets[0].x + 0.5, w.mallets[0].y))
        self.assertGreater(w.forces[0][0], 0.0)
        self.assertEqual(w.forces[1], (0.0, 0.0))       # the other mallet is untouched


class TestMouseMapping(unittest.TestCase):
    def setUp(self):
        self.world = make_world()
        self.layout = Layout.fit(self.world.arena, 900, 520)

    def test_the_cursor_lands_where_it_looks(self):
        # click the middle of the drawn table and land in the middle of the arena
        cx, cy = self.layout.to_pixels(self.world.arena.length_m / 2.0, self.world.arena.centre_y)
        x, y = self.layout.pixel_to_metres(cx, cy)
        self.assertAlmostEqual(x, self.world.arena.length_m / 2.0, places=9)
        self.assertAlmostEqual(y, self.world.arena.centre_y, places=9)

    def test_pixel_round_trip(self):
        for x_m, y_m in [(0.0, 0.0), (1.2192, 0.6096), (0.4, 0.2)]:
            px, py = self.layout.to_pixels(x_m, y_m)
            back_x, back_y = self.layout.pixel_to_metres(px, py)
            self.assertAlmostEqual(back_x, x_m, places=9)
            self.assertAlmostEqual(back_y, y_m, places=9)

    def test_the_near_goal_is_at_the_bottom_of_the_screen(self):
        _, bottom = self.layout.to_pixels(0.0, 0.0)
        _, top = self.layout.to_pixels(0.0, self.world.arena.width_m)
        self.assertGreater(bottom, top)

    def test_mouse_input_maps_a_pixel_to_a_target_and_a_force(self):
        mi = MouseInput(self.layout)
        px, py = self.layout.to_pixels(0.8, 0.4)
        mi.update_pointer((px, py))
        assert mi.target_m is not None
        self.assertAlmostEqual(mi.target_m[0], 0.8, places=9)
        fx, fy = mi.apply(self.world)
        self.assertGreater(fx, 0.0)                     # the mallet is behind the target
        self.assertNotEqual(self.world.forces[0], (0.0, 0.0))

    def test_no_pointer_means_no_force(self):
        mi = MouseInput(self.layout)
        self.assertEqual(mi.apply(self.world), (0.0, 0.0))
        self.assertEqual(self.world.forces[0], (0.0, 0.0))

    def test_a_cursor_outside_the_table_is_clamped_to_it(self):
        mi = MouseInput(self.layout)
        mi.update_pointer((-5000.0, -5000.0))
        mi.apply(self.world)
        for _ in range(600):
            self.world.step()
        m = self.world.mallets[0]
        self.assertGreaterEqual(m.y, m.radius - 1e-9)   # never left through the wall


class TestScriptedInput(unittest.TestCase):
    def test_the_mallet_reaches_a_scripted_target(self):
        w = make_world()
        si = ScriptedInput(target_m=(0.5, 0.35), controller=ForceController(mallet_index=0))
        for _ in range(2000):
            si.apply(w)
            w.step()
        self.assertAlmostEqual(w.mallets[0].x, 0.5, delta=0.01)
        self.assertAlmostEqual(w.mallets[0].y, 0.35, delta=0.01)

    def test_it_can_follow_the_puck(self):
        """Chasing a stationary puck ends in a contact, which shoves the puck, so the
        check is that the mallet stays on it rather than that it reaches a fixed point."""
        w = make_world()
        si = ScriptedInput(controller=ForceController(mallet_index=0))
        w.puck.launch(0.6, 0.25, 0.0, 0.0)
        touched = False
        closest = 9.9
        for _ in range(1500):
            si.aim_at_puck(w)
            si.apply(w)
            w.step()
            if w.last_contact is not None:
                touched = True
            closest = min(closest, math.hypot(w.mallets[0].x - w.puck.x,
                                              w.mallets[0].y - w.puck.y))
        self.assertTrue(touched, "the mallet never reached the puck")
        self.assertLess(closest, 0.08)          # it got to the contact distance
        self.assertLess(math.hypot(w.mallets[0].x - w.puck.x,
                                   w.mallets[0].y - w.puck.y), 0.30)

    def test_the_second_mallet_gets_no_input(self):
        w = make_world()
        si = ScriptedInput(target_m=(0.5, 0.35))
        for _ in range(500):
            si.apply(w)
            w.step()
        self.assertEqual(w.forces[1], (0.0, 0.0))
        self.assertEqual(w.mallets[1].speed, 0.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
