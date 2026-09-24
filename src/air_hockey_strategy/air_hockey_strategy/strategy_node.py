import rclpy
from rclpy.node import Node

from air_hockey_interfaces.msg import MalletCommand, PuckState

from .strategy_logic import compute_defense_target


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


class MirrorDefenseStrategy(Node):
    def __init__(self):
        super().__init__("air_hockey_strategy")

        self.declare_parameter("table_width_m", 0.6096)  # 24 in
        self.declare_parameter("table_length_m", 1.2192)  # 48 in

        self.declare_parameter("margin_m", 0.05)

        # Defense plane y, in table coordinates. Default uses y_min + margin.
        self.declare_parameter("defense_plane_y", 0.0)

        # Predict where the puck crosses the defense plane.
        self.declare_parameter("target_lpf_alpha", 1.0)  # 1.0 = no smoothing
        self.declare_parameter("vy_epsilon", 1e-6)

        self.width = float(self.get_parameter("table_width_m").value)
        self.length = float(self.get_parameter("table_length_m").value)
        self.x_min = -self.width / 2.0
        self.x_max = self.width / 2.0
        self.y_min = -self.length / 2.0
        self.y_max = self.length / 2.0

        self.margin = float(self.get_parameter("margin_m").value)

        defense_plane_y = float(self.get_parameter("defense_plane_y").value)
        if abs(defense_plane_y) < 1e-12:
            defense_plane_y = self.y_min + self.margin
        self.defense_plane_y = defense_plane_y

        self.alpha = float(self.get_parameter("target_lpf_alpha").value)
        self.vy_epsilon = float(self.get_parameter("vy_epsilon").value)

        self.pub_cmd = self.create_publisher(MalletCommand, "/air_hockey/mallet_command", 10)
        self.sub_puck = self.create_subscription(
            PuckState,
            "/air_hockey/puck_state",
            self._on_puck,
            10,
        )

        self.have_last = False
        self.last_tx = 0.0
        self.last_ty = 0.0

    def _on_puck(self, msg: PuckState):
        px = float(msg.x)
        py = float(msg.y)
        vx = float(msg.vx)
        vy = float(msg.vy)

        target = compute_defense_target(
            px=px,
            py=py,
            vx=vx,
            vy=vy,
            defense_plane_y=self.defense_plane_y,
            x_min=self.x_min,
            x_max=self.x_max,
            y_min=self.y_min,
            y_max=self.y_max,
            margin=self.margin,
            vy_epsilon=self.vy_epsilon,
        )

        if not self.have_last:
            self.last_tx = target.x
            self.last_ty = target.y
            self.have_last = True
        else:
            a = self.alpha
            self.last_tx = a * target.x + (1.0 - a) * self.last_tx
            self.last_ty = a * target.y + (1.0 - a) * self.last_ty

        out = MalletCommand()
        out.target_x = float(self.last_tx)
        out.target_y = float(self.last_ty)
        self.pub_cmd.publish(out)


def main():
    rclpy.init()
    node = MirrorDefenseStrategy()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
