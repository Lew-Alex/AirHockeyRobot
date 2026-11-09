#!/usr/bin/env python3
"""Air-hockey physics, Pygame demo, and PPO training environment."""

from __future__ import annotations

import math
import random
from collections import deque
from collections.abc import Sequence
from typing import Any

import pygame


# -------------------- Simulation Constants --------------------

WINDOW_WIDTH  = 700
WINDOW_HEIGHT = 900
FPS           = 120

TABLE_MARGIN = 45
TABLE_RECT = pygame.Rect(
    TABLE_MARGIN,
    TABLE_MARGIN,
    WINDOW_WIDTH - 2 * TABLE_MARGIN,
    WINDOW_HEIGHT - 2 * TABLE_MARGIN,
)

GOAL_WIDTH = 230
GOAL_LEFT  = WINDOW_WIDTH // 2 - GOAL_WIDTH // 2
GOAL_RIGHT = GOAL_LEFT + GOAL_WIDTH


# Puck / mallet physics
PUCK_RADIUS              = 18
MALLET_RADIUS            = 30
PUCK_DRAG                = 32.0
PUCK_MAX_SPEED           = 500.0
MALLET_SPEED             = 520.0
MALLET_ACCELERATION      = 2_200.0
MALLET_VELOCITY_NOISE    = 22.0


# Simulated perception error
OBSERVATION_POSITION_NOISE = 2.5
OBSERVATION_VELOCITY_NOISE = 12.0


# PPO reward shaping
GOAL_REWARD             = 10.0
CONCEDED_GOAL_REWARD    = -10.0
RETURN_SHOT_REWARD      = 0.20
CONTACT_REWARD          = 0.05
TIME_PENALTY            = -0.001
MOVEMENT_PENALTY        = -0.0001
FORWARD_PROGRESS_REWARD = 0.0002
MALLET_POSITION_REWARD  = 0.001
APPROACH_REWARD         = 0.0005


# Display colors
BACKGROUND  = (18, 25, 32)
TABLE_COLOR = (28, 102, 122)
LINE_COLOR  = (218, 238, 240)
PUCK_COLOR  = (246, 211, 45)
USER_COLOR  = (239, 76, 86)
ROBOT_COLOR = (65, 153, 255)
TEXT_COLOR  = (240, 245, 247)


# -------------------- Physics Helpers --------------------

def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(value, maximum))


def reset_puck(
    direction: int | None = None,
    *,
    rng: random.Random | None = None,
) -> tuple[pygame.Vector2, pygame.Vector2]:
    """Launch a puck from table center toward either player."""
    random_source = rng or random

    if direction is None:
        direction = random_source.choice((-1, 1))

    angle = random_source.uniform(-0.65, 0.65)
    speed = random_source.uniform(155.0, 235.0)

    puck_position = pygame.Vector2(TABLE_RECT.center)
    puck_velocity = pygame.Vector2(
        math.sin(angle) * speed,
        direction * math.cos(angle) * speed,
    )

    return puck_position, puck_velocity


def get_observation(
    puck_position: pygame.Vector2,
    puck_velocity: pygame.Vector2,
    robot_position: pygame.Vector2,
    robot_velocity: pygame.Vector2,
    *,
    add_noise: bool = True,
    rng: random.Random | None = None,
) -> tuple[float, float, float, float, float, float, float, float]:
    """Return raw puck/robot measurements before PPO normalization."""
    random_source = rng or random
    position_noise = OBSERVATION_POSITION_NOISE if add_noise else 0.0
    velocity_noise = OBSERVATION_VELOCITY_NOISE if add_noise else 0.0

    # Simulates error from the camera tracker and motor encoders.
    def measure(value: float, standard_deviation: float) -> float:
        return value + random_source.gauss(0.0, standard_deviation)

    return (
        measure(puck_position.x, position_noise),
        measure(puck_position.y, position_noise),
        measure(puck_velocity.x, velocity_noise),
        measure(puck_velocity.y, velocity_noise),
        measure(robot_position.x, position_noise),
        measure(robot_position.y, position_noise),
        measure(robot_velocity.x, velocity_noise),
        measure(robot_velocity.y, velocity_noise),
    )


def keep_mallet_on_half(position: pygame.Vector2, *, top_half: bool) -> None:
    """Constrain a mallet to its own side of the centre line."""
    position.x = clamp(
        position.x,
        TABLE_RECT.left + MALLET_RADIUS,
        TABLE_RECT.right - MALLET_RADIUS,
    )

    if top_half:
        position.y = clamp(
            position.y,
            TABLE_RECT.top + MALLET_RADIUS,
            TABLE_RECT.centery - MALLET_RADIUS,
        )
    else:
        position.y = clamp(
            position.y,
            TABLE_RECT.centery + MALLET_RADIUS,
            TABLE_RECT.bottom - MALLET_RADIUS,
        )


def apply_robot_velocity(
    position: pygame.Vector2,
    actual_velocity: pygame.Vector2,
    velocity_x: float,
    velocity_y: float,
    dt: float,
    *,
    rng: random.Random | None = None,
) -> None:
    """Move the top-side robot from an imperfect X/Y velocity command."""
    random_source = rng or random
    command = pygame.Vector2(velocity_x, velocity_y)

    if command.length() > MALLET_SPEED:
        command.scale_to_length(MALLET_SPEED)

    # The real robot will not follow commands perfectly.
    if command.length_squared() > 0:
        command.x += random_source.gauss(0.0, MALLET_VELOCITY_NOISE)
        command.y += random_source.gauss(0.0, MALLET_VELOCITY_NOISE)

    # Acceleration limit prevents instantaneous direction changes.
    velocity_change = command - actual_velocity
    maximum_change = MALLET_ACCELERATION * dt

    if velocity_change.length() > maximum_change:
        velocity_change.scale_to_length(maximum_change)

    actual_velocity += velocity_change
    position += actual_velocity * dt

    # Stop the corresponding axis when the mallet hits a table boundary.
    unconstrained_position = position.copy()
    keep_mallet_on_half(position, top_half=True)

    if position.x != unconstrained_position.x:
        actual_velocity.x = 0.0

    if position.y != unconstrained_position.y:
        actual_velocity.y = 0.0


def apply_user_velocity(
    position: pygame.Vector2,
    actual_velocity: pygame.Vector2,
    velocity_x: float,
    velocity_y: float,
    dt: float,
) -> None:
    """Move the bottom-side user mallet perfectly for manual testing."""
    command = pygame.Vector2(velocity_x, velocity_y)

    if command.length() > MALLET_SPEED:
        command.scale_to_length(MALLET_SPEED)

    actual_velocity.update(command)
    position += actual_velocity * dt

    unconstrained_position = position.copy()
    keep_mallet_on_half(position, top_half=False)

    if position.x != unconstrained_position.x:
        actual_velocity.x = 0.0

    if position.y != unconstrained_position.y:
        actual_velocity.y = 0.0


def collide_puck_with_mallet(
    puck_position: pygame.Vector2,
    puck_velocity: pygame.Vector2,
    mallet_position: pygame.Vector2,
    mallet_velocity: pygame.Vector2,
) -> bool:
    """Resolve a collision and return whether the puck was actively struck."""
    offset = puck_position - mallet_position
    minimum_distance = PUCK_RADIUS + MALLET_RADIUS
    distance_squared = offset.length_squared()

    if distance_squared >= minimum_distance * minimum_distance:
        return False

    if distance_squared == 0:
        normal, distance = pygame.Vector2(0, -1), 0.0
    else:
        distance = math.sqrt(distance_squared)
        normal = offset / distance

    # Separate overlapping objects before calculating their new velocities.
    puck_position += normal * (minimum_distance - distance)

    relative_velocity = puck_velocity - mallet_velocity
    speed_into_mallet = relative_velocity.dot(normal)

    if speed_into_mallet >= 0:
        return False

    # Reflect the puck and transfer some mallet velocity into the shot.
    puck_velocity -= 1.92 * speed_into_mallet * normal
    puck_velocity += mallet_velocity * 0.30

    if puck_velocity.length() > PUCK_MAX_SPEED:
        puck_velocity.scale_to_length(PUCK_MAX_SPEED)

    return True


def update_puck(position: pygame.Vector2, velocity: pygame.Vector2, dt: float) -> int:
    """Advance puck physics. Return +1 for a user goal, -1 for a robot goal."""
    position += velocity * dt

    # Linear drag lets a puck eventually come fully to rest.
    speed = velocity.length()

    if speed <= PUCK_DRAG * dt:
        velocity.update(0.0, 0.0)
    elif speed > 0:
        velocity.scale_to_length(speed - PUCK_DRAG * dt)

    # Side-wall bounces.
    if position.x - PUCK_RADIUS < TABLE_RECT.left:
        position.x = TABLE_RECT.left + PUCK_RADIUS
        velocity.x = abs(velocity.x)
    elif position.x + PUCK_RADIUS > TABLE_RECT.right:
        position.x = TABLE_RECT.right - PUCK_RADIUS
        velocity.x = -abs(velocity.x)

    # Top goal belongs to the user. Bottom goal belongs to the robot.
    inside_goal = GOAL_LEFT < position.x < GOAL_RIGHT

    if position.y - PUCK_RADIUS < TABLE_RECT.top:
        if inside_goal:
            return 1
        position.y = TABLE_RECT.top + PUCK_RADIUS
        velocity.y = abs(velocity.y)
    elif position.y + PUCK_RADIUS > TABLE_RECT.bottom:
        if inside_goal:
            return -1
        position.y = TABLE_RECT.bottom - PUCK_RADIUS
        velocity.y = -abs(velocity.y)

    return 0


def reflect_x_at_table_walls(x_position: float) -> float:
    """Fold an X position back into the table as if it bounced off side walls."""
    left = TABLE_RECT.left + PUCK_RADIUS
    right = TABLE_RECT.right - PUCK_RADIUS
    span = right - left
    wrapped = (x_position - left) % (2 * span)
    return left + wrapped if wrapped <= span else right - (wrapped - span)


# -------------------- Baseline Controller --------------------

def simple_defence_action(environment: "AirHockeyEnv") -> pygame.Vector2:
    """Move only to protect the robot goal. Used as a simple PPO baseline."""
    home = pygame.Vector2(TABLE_RECT.centerx, TABLE_RECT.top + 90)
    target = home

    puck_is_incoming = environment.puck_velocity.y < -1

    if puck_is_incoming:
        time_to_robot = (
            home.y - environment.puck_position.y
        ) / environment.puck_velocity.y

        if time_to_robot >= 0:
            projected_x = (
                environment.puck_position.x
                + environment.puck_velocity.x * time_to_robot
            )
            target.x = reflect_x_at_table_walls(projected_x)

    # The returned value is a normalized velocity action in [-1, 1].
    direction = target - environment.robot_position

    if direction.length() < 4:
        return pygame.Vector2()

    return direction.normalize()


# -------------------- PPO Environment --------------------

class AirHockeyEnv:
    """One-step-at-a-time environment for the hand-written PPO trainer.

    ``reset()`` returns a normalized noisy observation. ``step(action)`` takes
    a two-value robot velocity action in [-1, 1] and returns:
    ``observation, reward, terminated, truncated, info``.
    """

    def __init__(
        self,
        *,
        dt: float = 1 / 60,
        max_steps: int = 1_800,
        add_observation_noise: bool = True,
        seed: int | None = None,
    ) -> None:
        self.dt = dt
        self.max_steps = max_steps
        self.add_observation_noise = add_observation_noise
        self.rng = random.Random(seed)

        self.step_count = 0
        self.robot_score = 0
        self.user_score = 0

        self.puck_position = pygame.Vector2()
        self.puck_velocity = pygame.Vector2()
        self.robot_position = pygame.Vector2()
        self.robot_velocity = pygame.Vector2()
        self.user_position = pygame.Vector2()
        self.user_velocity = pygame.Vector2()
        self.reset()

    def reset(self, *, seed: int | None = None) -> tuple[float, ...]:
        """Start a randomized round and return its first policy observation."""
        if seed is not None:
            self.rng.seed(seed)

        self.step_count = 0
        self.puck_position, self.puck_velocity = reset_puck(rng=self.rng)

        # Robot starts at the top. User starts at the bottom.
        self.robot_position.update(TABLE_RECT.centerx, TABLE_RECT.top + 90)
        self.robot_velocity.update(0.0, 0.0)
        self.user_position.update(TABLE_RECT.centerx, TABLE_RECT.bottom - 90)
        self.user_velocity.update(0.0, 0.0)

        return self.observation()

    def observation(self) -> tuple[float, ...]:
        """Return the normalized, noisy eight-value state seen by the policy."""
        raw = get_observation(
            self.puck_position,
            self.puck_velocity,
            self.robot_position,
            self.robot_velocity,
            add_noise=self.add_observation_noise,
            rng=self.rng,
        )

        # Normalize positions and velocities so neural-network inputs stay small.
        half_width = TABLE_RECT.width / 2
        half_height = TABLE_RECT.height / 2

        return (
            (raw[0] - TABLE_RECT.centerx) / half_width,
            (raw[1] - TABLE_RECT.centery) / half_height,
            raw[2] / PUCK_MAX_SPEED,
            raw[3] / PUCK_MAX_SPEED,
            (raw[4] - TABLE_RECT.centerx) / half_width,
            (raw[5] - TABLE_RECT.centery) / half_height,
            raw[6] / MALLET_SPEED,
            raw[7] / MALLET_SPEED,
        )

    def scripted_user_action(self) -> pygame.Vector2:
        """A basic opponent that defends its own goal and follows incoming pucks."""
        home = pygame.Vector2(TABLE_RECT.centerx, TABLE_RECT.bottom - 90)
        target = home

        if self.puck_position.y > TABLE_RECT.centery or self.puck_velocity.y > 0:
            target = pygame.Vector2(
                clamp(
                    self.puck_position.x,
                    TABLE_RECT.left + MALLET_RADIUS,
                    TABLE_RECT.right - MALLET_RADIUS,
                ),
                TABLE_RECT.bottom - 100,
            )

        direction = target - self.user_position

        if direction.length() < 5:
            return pygame.Vector2()

        return direction.normalize() * 0.82

    def _reward(
        self,
        *,
        goal: int,
        robot_hit: bool,
        puck_y_before_step: float,
        robot_dy: float,
        puck_distance_closed: float,
        action: pygame.Vector2,
    ) -> tuple[float, dict[str, float]]:
        """Reward one policy decision. Goal rewards dominate all shaping."""
        parts: dict[str, float] = {"time": TIME_PENALTY}

        if goal == -1:
            parts["goal"] = GOAL_REWARD
        elif goal == 1:
            parts["goal"] = CONCEDED_GOAL_REWARD
        else:
            if robot_hit:
                parts["contact"] = CONTACT_REWARD

                if self.puck_velocity.y > 0:
                    parts["return_shot"] = RETURN_SHOT_REWARD

            # Positive Y is toward the user goal because the robot is on top.
            parts["forward_progress"] = FORWARD_PROGRESS_REWARD * (
                self.puck_position.y - puck_y_before_step
            )
            puck_on_our_side = puck_y_before_step < TABLE_RECT.centery
            parts["mallet_position"] = MALLET_POSITION_REWARD * (
                robot_dy if puck_on_our_side else -robot_dy
            )
            if puck_on_our_side:
                parts["approach"] = APPROACH_REWARD * puck_distance_closed
            parts["movement"] = MOVEMENT_PENALTY * action.length_squared()

        return sum(parts.values()), parts

    def step(
        self,
        action: Sequence[float],
        *,
        user_action: Sequence[float] | None = None,
    ) -> tuple[tuple[float, ...], float, bool, bool, dict[str, Any]]:
        """Advance one fixed step using a normalized [velocity_x, velocity_y] action."""
        if len(action) != 2:
            raise ValueError("Robot action must contain exactly [velocity_x, velocity_y].")

        clipped_action = pygame.Vector2(
            clamp(float(action[0]), -1.0, 1.0),
            clamp(float(action[1]), -1.0, 1.0),
        )

        if clipped_action.length() > 1:
            clipped_action.scale_to_length(1)

        robot_command = clipped_action * MALLET_SPEED

        # Use a scripted opponent during training unless a manual action is given.
        if user_action is None:
            normalized_user_action = self.scripted_user_action()
        else:
            if len(user_action) != 2:
                raise ValueError("User action must contain exactly [velocity_x, velocity_y].")

            normalized_user_action = pygame.Vector2(
                clamp(float(user_action[0]), -1.0, 1.0),
                clamp(float(user_action[1]), -1.0, 1.0),
            )

            if normalized_user_action.length() > 1:
                normalized_user_action.scale_to_length(1)

        # Update both mallets.
        robot_y_before_step = self.robot_position.y
        puck_distance_before_step = self.robot_position.distance_to(self.puck_position)
        apply_robot_velocity(
            self.robot_position,
            self.robot_velocity,
            robot_command.x,
            robot_command.y,
            self.dt,
            rng=self.rng,
        )

        user_command = normalized_user_action * MALLET_SPEED
        apply_user_velocity(
            self.user_position,
            self.user_velocity,
            user_command.x,
            user_command.y,
            self.dt,
        )

        # Resolve hits, then update puck motion and goal state.
        puck_y_before_step = self.puck_position.y
        robot_hit = collide_puck_with_mallet(
            self.puck_position,
            self.puck_velocity,
            self.robot_position,
            self.robot_velocity,
        )
        user_hit = collide_puck_with_mallet(
            self.puck_position,
            self.puck_velocity,
            self.user_position,
            self.user_velocity,
        )
        goal = update_puck(self.puck_position, self.puck_velocity, self.dt)

        self.step_count += 1
        reward, reward_parts = self._reward(
            goal=goal,
            robot_hit=robot_hit,
            puck_y_before_step=puck_y_before_step,
            robot_dy=self.robot_position.y - robot_y_before_step,
            puck_distance_closed=puck_distance_before_step - self.robot_position.distance_to(self.puck_position),
            action=clipped_action,
        )

        terminated = goal != 0
        truncated = self.step_count >= self.max_steps

        if goal == -1:
            self.robot_score += 1
        elif goal == 1:
            self.user_score += 1

        info: dict[str, Any] = {
            "goal": goal,
            "robot_hit": robot_hit,
            "user_hit": user_hit,
            "reward_parts": reward_parts,
            "step_count": self.step_count,
        }

        return self.observation(), reward, terminated, truncated, info

    def render(self, surface: pygame.Surface, font: pygame.font.Font) -> None:
        """Draw the current environment state. Rendering is separate from training."""
        surface.fill(BACKGROUND)
        draw_table(surface)
        pygame.draw.circle(surface, PUCK_COLOR, self.puck_position, PUCK_RADIUS)
        pygame.draw.circle(surface, ROBOT_COLOR, self.robot_position, MALLET_RADIUS)
        pygame.draw.circle(surface, LINE_COLOR, self.robot_position, MALLET_RADIUS, width=3)
        pygame.draw.circle(surface, USER_COLOR, self.user_position, MALLET_RADIUS)
        pygame.draw.circle(surface, LINE_COLOR, self.user_position, MALLET_RADIUS, width=3)

        score = font.render(
            f"Robot {self.robot_score}   |   User {self.user_score}",
            True,
            TEXT_COLOR,
        )
        surface.blit(score, (TABLE_RECT.left, 10))

    def close(self) -> None:
        """Reserved for future resources; the trainer gets a standard API now."""


# -------------------- Pygame Display --------------------

def draw_table(surface: pygame.Surface) -> None:
    """Draw table geometry only. Game objects are drawn by AirHockeyEnv.render."""
    pygame.draw.rect(surface, TABLE_COLOR, TABLE_RECT, border_radius=26)
    pygame.draw.rect(surface, LINE_COLOR, TABLE_RECT, width=4, border_radius=26)
    pygame.draw.line(
        surface,
        LINE_COLOR,
        (TABLE_RECT.left, TABLE_RECT.centery),
        (TABLE_RECT.right, TABLE_RECT.centery),
        width=3,
    )
    pygame.draw.circle(surface, LINE_COLOR, TABLE_RECT.center, 75, width=3)
    pygame.draw.line(
        surface,
        BACKGROUND,
        (GOAL_LEFT, TABLE_RECT.top),
        (GOAL_RIGHT, TABLE_RECT.top),
        width=7,
    )
    pygame.draw.line(
        surface,
        BACKGROUND,
        (GOAL_LEFT, TABLE_RECT.bottom),
        (GOAL_RIGHT, TABLE_RECT.bottom),
        width=7,
    )


def reward_test() -> int:
    pygame.init()
    screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
    pygame.display.set_caption("Air Hockey reward test")
    clock = pygame.time.Clock()
    font = pygame.font.Font(None, 29)
    environment = AirHockeyEnv()
    environment.reset()
    recent_parts = deque(maxlen=50)
    running = True

    while running:
        clock.tick(FPS)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_SPACE:
                    environment.reset()
                    recent_parts.clear()

        keys = pygame.key.get_pressed()
        robot_action = pygame.Vector2(
            int(keys[pygame.K_d] or keys[pygame.K_RIGHT]) - int(keys[pygame.K_a] or keys[pygame.K_LEFT]),
            int(keys[pygame.K_s] or keys[pygame.K_DOWN]) - int(keys[pygame.K_w] or keys[pygame.K_UP]),
        )

        _, reward, terminated, truncated, info = environment.step(robot_action)

        recent_parts.append(info["reward_parts"])
        recent_by_part = {}
        for parts in recent_parts:
            for name, value in parts.items():
                recent_by_part[name] = recent_by_part.get(name, 0) + value
        recent_total = sum(recent_by_part.values())

        if environment.step_count % 50 == 0:
            print(f"last 50 steps: {recent_total:+.3f}", {n: round(v, 3) for n, v in recent_by_part.items()})

        environment.render(screen, font)
        total_text = font.render(f"reward, last {len(recent_parts)} steps: {recent_total:+.3f}", True, TEXT_COLOR)
        step_text = font.render(f"you (blue): ({robot_action.x:+.2f}, {robot_action.y:+.2f})  reward={reward:+.3f}", True, TEXT_COLOR)
        controls = font.render("Reward test: WASD or arrows   Space: reset   Esc: quit", True, TEXT_COLOR)
        screen.blit(total_text, (GOAL_LEFT, 12))
        screen.blit(step_text, (TABLE_RECT.left, WINDOW_HEIGHT - 55))
        screen.blit(controls, (TABLE_RECT.left, WINDOW_HEIGHT - 29))
        pygame.display.flip()

        if terminated or truncated:
            environment.reset()

    environment.close()
    pygame.quit()
    return 0


def main() -> int:
    """Run a visual test with an untrained policy or arrow-key robot control."""
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--test_rewards",
        nargs="?",
        const=True,
        default=False,
        type=lambda value: value.lower() in ("true", "1", "yes"),
        help="Control the blue mallet yourself against the scripted opponent and see its reward. No AI is used.",
    )
    if parser.parse_args().test_rewards:
        return reward_test()

    import torch

    from policy import ActorCritic

    pygame.init()
    screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
    pygame.display.set_caption("Air Hockey AI Simulation")
    clock = pygame.time.Clock()
    font = pygame.font.Font(None, 29)
    environment = AirHockeyEnv()
    observation = environment.reset()
    policy = ActorCritic()

    # Modes: random NN output, rule-based defender, or manual arrow control.
    control_mode = "untrained_actor"
    running = True

    while running:
        clock.tick(FPS)

        # Window and mode controls.
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_SPACE:
                    observation = environment.reset()
                elif event.key == pygame.K_n:
                    control_mode = (
                        "basic_defence"
                        if control_mode == "untrained_actor"
                        else "untrained_actor"
                    )
                elif event.key == pygame.K_m:
                    control_mode = "manual"

        # Red player is always perfect WASD control in the visual demo.
        keys = pygame.key.get_pressed()
        user_action = pygame.Vector2(
            int(keys[pygame.K_d]) - int(keys[pygame.K_a]),
            int(keys[pygame.K_s]) - int(keys[pygame.K_w]),
        )

        # Choose the blue robot's source of velocity commands.
        if control_mode == "untrained_actor":
            with torch.no_grad():
                policy_input = torch.tensor(observation, dtype=torch.float32)
                _, policy_action, _, _ = policy.act(policy_input, explore=True)

            robot_action = pygame.Vector2(policy_action.tolist())
            control_name = "untrained PPO (random exploration)"
        elif control_mode == "basic_defence":
            robot_action = simple_defence_action(environment)
            control_name = "basic defender"
        else:
            robot_action = pygame.Vector2(
                int(keys[pygame.K_RIGHT]) - int(keys[pygame.K_LEFT]),
                int(keys[pygame.K_DOWN]) - int(keys[pygame.K_UP]),
            )
            control_name = "arrow-key robot"

        observation, reward, terminated, truncated, _ = environment.step(
            robot_action,
            user_action=user_action,
        )

        environment.render(screen, font)
        command_text = font.render(
            f"{control_name}: ({robot_action.x:+.2f}, {robot_action.y:+.2f})  reward={reward:+.3f}",
            True,
            TEXT_COLOR,
        )
        controls = font.render(
            "User: WASD   N: actor/defender   M: manual arrows   Space: reset",
            True,
            TEXT_COLOR,
        )
        screen.blit(command_text, (TABLE_RECT.left, WINDOW_HEIGHT - 55))
        screen.blit(controls, (TABLE_RECT.left, WINDOW_HEIGHT - 29))
        pygame.display.flip()

        if terminated or truncated:
            observation = environment.reset()

    environment.close()
    pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
