import math
import os
import sys
import unittest

# Allow running tests without an installed ROS workspace.
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
SIM_PKG_ROOT = os.path.join(REPO_ROOT, "src", "air_hockey_sim")
sys.path.insert(0, SIM_PKG_ROOT)

from air_hockey_sim.sim_logic import (  # noqa: E402
    Bounds,
    bounce_off_walls,
    collide_puck_with_mallet,
    limit_mallet_velocity,
    step_puck,
)

BOUNDS = Bounds(x_min=-1.0, x_max=1.0, y_min=-2.0, y_max=2.0)


class TestStepPuck(unittest.TestCase):
    def test_drag_and_position_advance(self):
        px, py, vx, vy = step_puck(0.0, 0.0, 10.0, 0.0, drag=0.02, dt=0.01)
        expected_v = 10.0 * math.exp(-0.02 * 0.01)
        self.assertAlmostEqual(vx, expected_v, places=9)
        self.assertAlmostEqual(vy, 0.0, places=9)
        self.assertAlmostEqual(px, expected_v * 0.01, places=9)
        self.assertAlmostEqual(py, 0.0, places=9)


class TestBounceOffWalls(unittest.TestCase):
    def test_reflects_and_places_inside_at_min_x(self):
        x, y, vx, vy = bounce_off_walls(-0.95, 0.0, -3.0, 0.0, 0.1, BOUNDS, 0.9)
        self.assertAlmostEqual(vx, 2.7)
        self.assertAlmostEqual(x, -0.9)
        self.assertAlmostEqual(vy, 0.0)

    def test_does_not_flip_a_puck_already_leaving(self):
        x, y, vx, vy = bounce_off_walls(-0.95, 0.0, 3.0, 0.0, 0.1, BOUNDS, 0.9)
        self.assertAlmostEqual(vx, 3.0)
        self.assertAlmostEqual(x, -0.95)

    def test_reflects_at_max_y(self):
        x, y, vx, vy = bounce_off_walls(0.0, 1.95, 0.0, 4.0, 0.1, BOUNDS, 0.5)
        self.assertAlmostEqual(vy, -2.0)
        self.assertAlmostEqual(y, 1.9)

    def test_far_from_every_wall_is_untouched(self):
        x, y, vx, vy = bounce_off_walls(0.2, 0.3, 1.0, -1.0, 0.1, BOUNDS, 0.9)
        self.assertEqual((x, y, vx, vy), (0.2, 0.3, 1.0, -1.0))


class TestPuckMalletCollision(unittest.TestCase):
    def test_head_on_elastic_reverses_and_rebounds(self):
        # Puck at 1 m/s to the right, mallet 1 m/s to the left, closing.
        px, py, pvx, pvy = collide_puck_with_mallet(
            0.0, 0.0, 1.0, 0.0, 0.05, 0.0, -1.0, 0.0, 0.05, 0.05, 1.0
        )
        # Relative normal speed was -2, so the puck leaves at -3.
        self.assertAlmostEqual(pvx, -3.0)
        self.assertAlmostEqual(pvy, 0.0)
        # Pushed clear of the mallet on the normal that points from the mallet to the puck.
        self.assertLess(px, 0.05 - 0.05)
        self.assertAlmostEqual(py, 0.0)

    def test_less_than_fully_elastic(self):
        px, py, pvx, pvy = collide_puck_with_mallet(
            0.0, 0.0, 1.0, 0.0, 0.05, 0.0, -1.0, 0.0, 0.05, 0.05, 0.8
        )
        self.assertAlmostEqual(pvx, -2.6)

    def test_separating_puck_is_not_impulsed_but_is_separated(self):
        # Puck moving away from the mallet while overlapping.
        px, py, pvx, pvy = collide_puck_with_mallet(
            0.0, 0.0, -2.0, 0.0, 0.05, 0.0, 0.0, 0.0, 0.05, 0.05, 0.8
        )
        self.assertAlmostEqual(pvx, -2.0)
        self.assertAlmostEqual(pvy, 0.0)

    def test_no_contact_leaves_everything_alone(self):
        px, py, pvx, pvy = collide_puck_with_mallet(
            0.5, 0.5, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.02, 0.03, 0.8
        )
        self.assertEqual((px, py, pvx, pvy), (0.5, 0.5, 1.0, 1.0))

    def test_result_is_always_outside_the_sum_of_radii(self):
        px, py, pvx, pvy = collide_puck_with_mallet(
            0.0, 0.0, 1.0, 0.0, 0.02, 0.02, -1.0, 0.0, 0.05, 0.05, 0.8
        )
        dist = math.hypot(px - 0.02, py - 0.02)
        self.assertGreaterEqual(dist, 0.1)

    def test_concentric_overlap_does_not_divide_by_zero(self):
        px, py, pvx, pvy = collide_puck_with_mallet(
            0.1, 0.1, 1.0, 0.0, 0.1, 0.1, -1.0, 0.0, 0.05, 0.05, 0.8
        )
        self.assertTrue(math.isfinite(px) and math.isfinite(py))
        self.assertTrue(math.isfinite(pvx) and math.isfinite(pvy))


class TestLimitMalletVelocity(unittest.TestCase):
    def test_acceleration_limit_caps_the_step(self):
        mvx, mvy = limit_mallet_velocity(0.0, 0.0, 100.0, 0.0, a_max=20.0, dt=0.01, v_max=10.0)
        self.assertAlmostEqual(mvx, 0.2)
        self.assertAlmostEqual(mvy, 0.0)

    def test_speed_limit_is_never_exceeded(self):
        mvx, mvy = limit_mallet_velocity(0.0, 0.0, 100.0, 100.0, a_max=1e6, dt=0.01, v_max=10.0)
        self.assertAlmostEqual(math.hypot(mvx, mvy), 10.0)

    def test_direction_of_the_acceleration_step_is_preserved(self):
        mvx, mvy = limit_mallet_velocity(0.0, 0.0, 3.0, 4.0, a_max=100.0, dt=0.01, v_max=10.0)
        # The step is capped at a_max * dt = 1.0 m/s, applied along the (3,4) direction, so
        # the result is 1.0 m/s in that direction: (0.6, 0.8).
        self.assertAlmostEqual(mvx, 0.6)
        self.assertAlmostEqual(mvy, 0.8)
        self.assertAlmostEqual(math.hypot(mvx, mvy), 1.0)

    def test_reaching_the_command_needs_no_more_than_one_step(self):
        mvx, mvy = limit_mallet_velocity(1.0, 2.0, 1.5, 2.5, a_max=100.0, dt=0.01, v_max=10.0)
        self.assertAlmostEqual(mvx, 1.5)
        self.assertAlmostEqual(mvy, 2.5)


if __name__ == "__main__":
    unittest.main()
