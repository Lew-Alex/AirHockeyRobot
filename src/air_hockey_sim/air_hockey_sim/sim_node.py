import rclpy
from rclpy.node import Node

from air_hockey_interfaces.msg import GantryVelocity, MalletPose, PuckState

from .sim_logic import (
    Bounds,
    bounce_off_walls,
    clamp,
    collide_puck_with_mallet,
    limit_mallet_velocity,
    step_puck,
)

PUCK_MALLET_RESTITUTION = 0.8


class AirHockeySim(Node):
    def __init__(self):
        super().__init__("air_hockey_sim")

        # Table bounds, centre at (0, 0)
        self.declare_parameter("table_width_m", 0.6096)  # 24 in
        self.declare_parameter("table_length_m", 1.2192)  # 48 in

        # Puck
        self.declare_parameter("puck_radius_m", 0.02)
        self.declare_parameter("puck_drag", 0.02)  # 1/s
        self.declare_parameter("wall_restitution", 0.9)

        # Mallet
        self.declare_parameter("mallet_radius_m", 0.03)
        self.declare_parameter("mallet_accel_limit", 20.0)  # m/s^2
        self.declare_parameter("mallet_max_speed", 10.0)  # m/s

        # Initial state
        self.declare_parameter("init_puck_x_m", 0.0)
        self.declare_parameter("init_puck_y_m", 0.2)
        self.declare_parameter("init_puck_vx_m_s", 1.5)
        self.declare_parameter("init_puck_vy_m_s", 3.0)
        self.declare_parameter("init_mallet_x_m", 0.0)
        self.declare_parameter("init_mallet_y_m", -0.45)

        self.declare_parameter("publish_rate_hz", 200.0)

        width = float(self.get_parameter("table_width_m").value)
        length = float(self.get_parameter("table_length_m").value)
        self.bounds = Bounds(
            x_min=-width / 2.0,
            x_max=width / 2.0,
            y_min=-length / 2.0,
            y_max=length / 2.0,
        )

        self.puck_r = float(self.get_parameter("puck_radius_m").value)
        self.mallet_r = float(self.get_parameter("mallet_radius_m").value)
        self.drag = float(self.get_parameter("puck_drag").value)
        self.wall_e = float(self.get_parameter("wall_restitution").value)
        self.mallet_a_max = float(self.get_parameter("mallet_accel_limit").value)
        self.mallet_v_max = float(self.get_parameter("mallet_max_speed").value)

        self.px = float(self.get_parameter("init_puck_x_m").value)
        self.py = float(self.get_parameter("init_puck_y_m").value)
        self.pvx = float(self.get_parameter("init_puck_vx_m_s").value)
        self.pvy = float(self.get_parameter("init_puck_vy_m_s").value)

        self.mx = float(self.get_parameter("init_mallet_x_m").value)
        self.my = float(self.get_parameter("init_mallet_y_m").value)
        self.mvx = 0.0
        self.mvy = 0.0

        # The gantry controller commands a planar velocity; this node integrates it.
        self.target_vx = 0.0
        self.target_vy = 0.0

        self.sub_gantry_velocity = self.create_subscription(
            GantryVelocity,
            "/air_hockey/gantry_velocity",
            self._on_gantry_velocity,
            10,
        )

        self.pub_puck_state = self.create_publisher(PuckState, "/air_hockey/puck_state", 10)
        self.pub_mallet_pose = self.create_publisher(MalletPose, "/air_hockey/mallet_pose", 10)

        rate_hz = float(self.get_parameter("publish_rate_hz").value)
        self.dt = 1.0 / rate_hz
        self.timer = self.create_timer(self.dt, self._tick)

    def _on_gantry_velocity(self, msg: GantryVelocity):
        self.target_vx = float(msg.vx)
        self.target_vy = float(msg.vy)

    def _tick(self):
        self.px, self.py, self.pvx, self.pvy = step_puck(
            self.px, self.py, self.pvx, self.pvy, self.drag, self.dt
        )
        self.px, self.py, self.pvx, self.pvy = bounce_off_walls(
            self.px, self.py, self.pvx, self.pvy, self.puck_r, self.bounds, self.wall_e
        )
        self.px, self.py, self.pvx, self.pvy = collide_puck_with_mallet(
            self.px,
            self.py,
            self.pvx,
            self.pvy,
            self.mx,
            self.my,
            self.mvx,
            self.mvy,
            self.puck_r,
            self.mallet_r,
            PUCK_MALLET_RESTITUTION,
        )

        self.mvx, self.mvy = limit_mallet_velocity(
            self.mvx,
            self.mvy,
            self.target_vx,
            self.target_vy,
            self.mallet_a_max,
            self.dt,
            self.mallet_v_max,
        )

        self.mx += self.mvx * self.dt
        self.my += self.mvy * self.dt
        self.mx = clamp(self.mx, self.bounds.x_min + self.mallet_r, self.bounds.x_max - self.mallet_r)
        self.my = clamp(self.my, self.bounds.y_min + self.mallet_r, self.bounds.y_max - self.mallet_r)

        puck = PuckState()
        puck.x = float(self.px)
        puck.y = float(self.py)
        puck.vx = float(self.pvx)
        puck.vy = float(self.pvy)

        mallet = MalletPose()
        mallet.x = float(self.mx)
        mallet.y = float(self.my)

        self.pub_puck_state.publish(puck)
        self.pub_mallet_pose.publish(mallet)


def main():
    rclpy.init()
    node = AirHockeySim()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
