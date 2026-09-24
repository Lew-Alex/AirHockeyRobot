import os
import sys
import unittest

# Allow running tests without an installed ROS workspace.
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
STRATEGY_PKG_ROOT = os.path.join(REPO_ROOT, "src", "air_hockey_strategy")
sys.path.insert(0, STRATEGY_PKG_ROOT)

from air_hockey_strategy.strategy_logic import compute_defense_target


class TestStrategyLogic(unittest.TestCase):
    def test_intercept_when_puck_moving_towards_plane(self):
        target = compute_defense_target(
            px=0.0,
            py=0.0,
            vx=2.0,
            vy=1.0,
            defense_plane_y=0.5,
            x_min=-0.5,
            x_max=0.5,
            y_min=-1.0,
            y_max=1.0,
            margin=0.05,
            vy_epsilon=1e-6,
        )
        self.assertAlmostEqual(target.y, 0.5)
        self.assertAlmostEqual(target.x, 0.45)

    def test_mirror_fallback_when_not_crossing(self):
        target = compute_defense_target(
            px=0.1,
            py=0.2,
            vx=0.0,
            vy=0.0,
            defense_plane_y=0.5,
            x_min=-0.5,
            x_max=0.5,
            y_min=-1.0,
            y_max=1.0,
            margin=0.05,
            vy_epsilon=1e-6,
        )
        self.assertAlmostEqual(target.x, 0.1)
        self.assertAlmostEqual(target.y, 0.8)

    def test_time_le_zero_uses_mirror(self):
        target = compute_defense_target(
            px=0.0,
            py=0.6,
            vx=1.0,
            vy=1.0,
            defense_plane_y=0.5,
            x_min=-0.5,
            x_max=0.5,
            y_min=-1.0,
            y_max=1.0,
            margin=0.05,
            vy_epsilon=1e-6,
        )
        self.assertAlmostEqual(target.y, 0.4)


if __name__ == "__main__":
    unittest.main()
