# Air Hockey Robot (ROS 2)

Three nodes in a closed loop, plus the message package they share:

| Package | Language | Role |
|---|---|---|
| `air_hockey_sim` | Python | Puck and mallet simulation. Publishes `/air_hockey/puck_state` and `/air_hockey/mallet_pose`, integrates `/air_hockey/gantry_velocity` into mallet motion. |
| `air_hockey_strategy` | Python | Predictive defence. Reads puck state, publishes `/air_hockey/mallet_command`. |
| `air_hockey_control` | C++ | Real-time gantry controller. Reads the command and the mallet pose, publishes `/air_hockey/gantry_velocity`. |
| `air_hockey_interfaces` | messages | `PuckState`, `MalletPose`, `MalletCommand`, `GantryVelocity`. |

The loop: sim -> strategy -> control -> sim.

```
/air_hockey/puck_state       sim      -> strategy
/air_hockey/mallet_command   strategy -> control
/air_hockey/gantry_velocity  control  -> sim
/air_hockey/mallet_pose      sim      -> control
```

## Layout

Each package splits the maths from the ROS plumbing, so the maths can be tested with no ROS running:

```
air_hockey_sim/air_hockey_sim/sim_logic.py            pure puck and mallet physics
air_hockey_sim/air_hockey_sim/sim_node.py             ROS interfaces only
air_hockey_strategy/air_hockey_strategy/strategy_logic.py   pure defence geometry
air_hockey_strategy/air_hockey_strategy/strategy_node.py    ROS interfaces only
air_hockey_control/src/gantry_controller_core.cpp     pure velocity law
air_hockey_control/src/gantry_controller_node.cpp     ROS interfaces only
```

## Speed envelope, and why it is a diamond

Belt A runs at `vx + vy` and belt B at `vx - vy`, so bounding the belt speed bounds the
reachable planar velocities to `|vx| + |vy| <= max_v_axis`. That gives `max_v_axis` straight
along an axis (10.0 m/s) and `max_v_axis / sqrt(2)` on the diagonal (7.071 m/s), which are the
two numbers the sizing study specifies. `max_v_diag` is therefore a consequence of the belt
limit, not an independent cap, and the controller warns at startup if the two disagree.

## Test without ROS

The pure modules need nothing but a compiler and Python:

```bash
cd ~/Documents/Github/AirHockeyRobot

# C++ velocity law: 27 assertions, including a 360 degree sweep of the envelope
clang++ -std=c++17 -I src/air_hockey_control/include \
  src/air_hockey_control/src/gantry_controller_core.cpp \
  src/air_hockey_control/test/standalone_core_check.cpp -o /tmp/core_check && /tmp/core_check

# Python physics and defence geometry
python3 -m unittest discover -s src/air_hockey_sim/test -p "test_*.py"
python3 -m unittest discover -s src/air_hockey_strategy/test -p "test_*.py"
```

## Build and run

```bash
cd ~/Documents/Github/AirHockeyRobot
source /opt/ros/<distro>/setup.bash
colcon build --symlink-install
source install/setup.bash
ros2 launch air_hockey_sim bringup.launch.py
```

Or the three nodes separately:

```bash
ros2 run air_hockey_sim sim_node --ros-args -p publish_rate_hz:=200.0
ros2 run air_hockey_strategy strategy_node --ros-args -p margin_m:=0.05
ros2 run air_hockey_control gantry_controller_node --ros-args \
  -p k_p:=4.0 -p max_v_axis:=10.0 -p max_v_diag:=7.07 -p publish_rate_hz:=200.0
```

Watch the loop with:

```bash
ros2 topic hz /air_hockey/puck_state
ros2 topic echo /air_hockey/mallet_command
ros2 topic echo /air_hockey/gantry_velocity
```

## Parameters

`air_hockey_sim`: `table_width_m` 0.6096, `table_length_m` 1.2192, `puck_radius_m` 0.02,
`puck_drag` 0.02, `wall_restitution` 0.9, `mallet_radius_m` 0.03, `mallet_accel_limit` 20.0,
`mallet_max_speed` 10.0, `init_puck_*`, `init_mallet_*`, `publish_rate_hz` 200.0.

`air_hockey_strategy`: `table_width_m`, `table_length_m`, `margin_m` 0.05, `defense_plane_y`
(defaults to the home rail plus `margin_m`), `target_lpf_alpha` 1.0, `vy_epsilon` 1e-6.

`air_hockey_control`: `k_p` 4.0, `max_v_axis` 10.0, `max_v_diag` 7.07, `publish_rate_hz` 200.0,
`stale_timeout_s` 0.25 (a command older than this is treated as silence and the controller
commands zero, so a dead strategy node cannot leave the gantry latched at speed).
