"""Bring up the three nodes of the air hockey loop.

  sim          publishes /air_hockey/puck_state and /air_hockey/mallet_pose
  strategy     turns puck state into /air_hockey/mallet_command
  control      turns that command into /air_hockey/gantry_velocity
  sim          integrates that velocity back into the mallet pose

Run with:
  ros2 launch air_hockey_sim bringup.launch.py
"""

from launch import LaunchDescription
from launch_ros.actions import Node

SIM_RATE_HZ = 200.0


def generate_launch_description():
    sim = Node(
        package="air_hockey_sim",
        executable="sim_node",
        name="air_hockey_sim",
        output="screen",
        parameters=[{"publish_rate_hz": SIM_RATE_HZ}],
    )

    strategy = Node(
        package="air_hockey_strategy",
        executable="strategy_node",
        name="air_hockey_strategy",
        output="screen",
        parameters=[{"margin_m": 0.05, "target_lpf_alpha": 1.0}],
    )

    # max_v_axis is the belt speed limit. The controller derives the 7.071 diagonal speed
    # from it and warns if max_v_diag disagrees.
    control = Node(
        package="air_hockey_control",
        executable="gantry_controller_node",
        name="gantry_controller_node",
        output="screen",
        parameters=[
            {
                "k_p": 4.0,
                "max_v_axis": 10.0,
                "max_v_diag": 7.07,
                "publish_rate_hz": SIM_RATE_HZ,
                "stale_timeout_s": 0.25,
            }
        ],
    )

    return LaunchDescription([sim, strategy, control])
