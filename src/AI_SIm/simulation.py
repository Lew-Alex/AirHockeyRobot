#!/usr/bin/env python3

import math
import random
from collections import deque

import pygame


# Sim constants

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
MOVEMENT_PENALTY        = 0.000001
FORWARD_PROGRESS_REWARD = 0.0002
MALLET_POSITION_REWARD  = 0.00075
APPROACH_REWARD         = 0.00125
HIT_DIRECTION_REWARD    = 0.20
HIT_BACKWARD_PENALTY    = -0.50
MISSED_PASS_PENALTY     = -0.50
MISSED_PASS_X_RANGE     = 100.0
PUCK_IN_FRONT_REWARD    = 0.0005


# Display colors
BACKGROUND  = (18, 25, 32)
TABLE_COLOR = (28, 102, 122)
LINE_COLOR  = (218, 238, 240)
PUCK_COLOR  = (246, 211, 45)
USER_COLOR  = (239, 76, 86)
ROBOT_COLOR = (65, 153, 255)
TEXT_COLOR  = (240, 245, 247)


# Physics stuff

def clamp(value, minimum, maximum):
    return max(minimum, min(value, maximum))


# Launches the puck from the center toward one of the players
def reset_puck(direction=None, rng=None):
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


# Raw puck + robot numbers before normalizing
def get_observation(puck_position, puck_velocity, robot_position, robot_velocity, add_noise=True, rng=None):
    random_source = rng or random
    position_noise = OBSERVATION_POSITION_NOISE if add_noise else 0.0
    velocity_noise = OBSERVATION_VELOCITY_NOISE if add_noise else 0.0

    # Adds error like the camera tracker + encoders would
    def measure(value, standard_deviation):
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


# Keeps a mallet on its own side of the center line
def keep_mallet_on_half(position, top_half):
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


# Moves the top robot from a velocity command (not perfect on purpose)
def apply_robot_velocity(position, actual_velocity, velocity_x, velocity_y, dt, rng=None):
    random_source = rng or random
    command = pygame.Vector2(velocity_x, velocity_y)

    if command.length() > MALLET_SPEED:
        command.scale_to_length(MALLET_SPEED)

    # Real robot won't follow commands perfectly
    if command.length_squared() > 0:
        command.x += random_source.gauss(0.0, MALLET_VELOCITY_NOISE)
        command.y += random_source.gauss(0.0, MALLET_VELOCITY_NOISE)

    # Acceleration limit so it can't turn instantly
    velocity_change = command - actual_velocity
    maximum_change = MALLET_ACCELERATION * dt

    if velocity_change.length() > maximum_change:
        velocity_change.scale_to_length(maximum_change)

    actual_velocity += velocity_change
    position += actual_velocity * dt

    # Stops that axis if the mallet hits a wall
    unconstrained_position = position.copy()
    keep_mallet_on_half(position, top_half=True)

    if position.x != unconstrained_position.x:
        actual_velocity.x = 0.0

    if position.y != unconstrained_position.y:
        actual_velocity.y = 0.0


# Moves the bottom (user) mallet perfectly
def apply_user_velocity(position, actual_velocity, velocity_x, velocity_y, dt):
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


# Handles a puck + mallet collision, returns True if the puck was actually hit
def collide_puck_with_mallet(puck_position, puck_velocity, mallet_position, mallet_velocity):
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

    # Push them apart first
    puck_position += normal * (minimum_distance - distance)

    relative_velocity = puck_velocity - mallet_velocity
    speed_into_mallet = relative_velocity.dot(normal)

    if speed_into_mallet >= 0:
        return False

    # Bounce the puck + add some of the mallet's speed
    puck_velocity -= 1.92 * speed_into_mallet * normal
    puck_velocity += mallet_velocity * 0.30

    if puck_velocity.length() > PUCK_MAX_SPEED:
        puck_velocity.scale_to_length(PUCK_MAX_SPEED)

    return True


# Moves the puck, returns 1 if the user scored, -1 if the robot scored, 0 otherwise
def update_puck(position, velocity, dt):
    position += velocity * dt

    # Drag so the puck can stop eventually
    speed = velocity.length()

    if speed <= PUCK_DRAG * dt:
        velocity.update(0.0, 0.0)
    elif speed > 0:
        velocity.scale_to_length(speed - PUCK_DRAG * dt)

    # Side wall bounces
    if position.x - PUCK_RADIUS < TABLE_RECT.left:
        position.x = TABLE_RECT.left + PUCK_RADIUS
        velocity.x = abs(velocity.x)
    elif position.x + PUCK_RADIUS > TABLE_RECT.right:
        position.x = TABLE_RECT.right - PUCK_RADIUS
        velocity.x = -abs(velocity.x)

    # Top goal is the user's, bottom goal is the robot's
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


# Folds an x position back into the table like it bounced off the side walls
def reflect_x_at_table_walls(x_position):
    left = TABLE_RECT.left + PUCK_RADIUS
    right = TABLE_RECT.right - PUCK_RADIUS
    span = right - left
    wrapped = (x_position - left) % (2 * span)
    return left + wrapped if wrapped <= span else right - (wrapped - span)



# Basic defender, only protects the robot goal
def simple_defence_action(environment):
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

    # Returned value is a velocity action between -1 and 1
    direction = target - environment.robot_position

    if direction.length() < 4:
        return pygame.Vector2()

    return direction.normalize()



# Training environment
# reset() gives the first observation
# step(action) takes a robot velocity [x, y] between -1 and 1 and gives back observation, reward, terminated, truncated, info
class AirHockeyEnv:

    def __init__(self, dt=1 / 60, max_steps=1_800, add_observation_noise=True, seed=None):
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

    # Starts a new round and returns the first observation
    def reset(self, seed=None):
        if seed is not None:
            self.rng.seed(seed)

        self.step_count = 0
        self.puck_position, self.puck_velocity = reset_puck(rng=self.rng)

        # Robot starts at the top, user at the bottom
        self.robot_position.update(TABLE_RECT.centerx, TABLE_RECT.top + 90)
        self.robot_velocity.update(0.0, 0.0)
        self.user_position.update(TABLE_RECT.centerx, TABLE_RECT.bottom - 90)
        self.user_velocity.update(0.0, 0.0)

        return self.observation()

    # The 8 numbers the policy sees (normalized + noisy)
    def observation(self):
        raw = get_observation(
            self.puck_position,
            self.puck_velocity,
            self.robot_position,
            self.robot_velocity,
            add_noise=self.add_observation_noise,
            rng=self.rng,
        )

        # Normalize so the network inputs stay small
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

    # Basic opponent, defends its goal and follows the puck
    def scripted_user_action(self):
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

    # Reward for one step, goals are way bigger than the shaping stuff
    def _reward(self, goal, robot_hit, puck_y_before_step, robot_dy, puck_distance_closed, action):
        parts = {"time": TIME_PENALTY}

        if goal == -1:
            parts["goal"] = GOAL_REWARD
        elif goal == 1:
            parts["goal"] = CONCEDED_GOAL_REWARD
        else:
            if robot_hit:
                parts["contact"] = CONTACT_REWARD

                # After a hit, faster toward the other goal = more reward, backwards costs a tiny bit
                if self.puck_velocity.y > 0:
                    parts["return_shot"] = RETURN_SHOT_REWARD
                    parts["hit_direction"] = HIT_DIRECTION_REWARD * self.puck_velocity.y / PUCK_MAX_SPEED
                else:
                    parts["hit_direction"] = HIT_BACKWARD_PENALTY

            # Positive y is toward the user's goal (robot is on top)
            parts["forward_progress"] = FORWARD_PROGRESS_REWARD * (
                self.puck_position.y - puck_y_before_step
            )
            puck_on_our_side = puck_y_before_step < TABLE_RECT.centery
            parts["mallet_position"] = MALLET_POSITION_REWARD * (
                robot_dy if puck_on_our_side else -robot_dy
            )
            if puck_on_our_side:
                parts["approach"] = APPROACH_REWARD * puck_distance_closed

            # Puck and mallet swapped y order this step, lined up in x, and never touched
            robot_y_before_step = self.robot_position.y - robot_dy
            swapped_y = (puck_y_before_step - robot_y_before_step) * (self.puck_position.y - self.robot_position.y) < 0
            lined_up = abs(self.puck_position.x - self.robot_position.x) < MISSED_PASS_X_RANGE
            touching = self.robot_position.distance_to(self.puck_position) <= PUCK_RADIUS + MALLET_RADIUS
            if swapped_y and lined_up and not robot_hit and not touching:
                parts["missed_pass"] = MISSED_PASS_PENALTY

            # Puck in front of the mallet (toward the user's goal) gets a small reward every step, behind gets nothing
            if self.puck_position.y > self.robot_position.y:
                parts["puck_in_front"] = PUCK_IN_FRONT_REWARD
            parts["movement"] = MOVEMENT_PENALTY * action.length_squared()

        return sum(parts.values()), parts

    # Plays one step
    def step(self, action, user_action=None):
        if len(action) != 2:
            raise ValueError("Robot action must contain exactly [velocity_x, velocity_y].")

        clipped_action = pygame.Vector2(
            clamp(float(action[0]), -1.0, 1.0),
            clamp(float(action[1]), -1.0, 1.0),
        )

        if clipped_action.length() > 1:
            clipped_action.scale_to_length(1)

        robot_command = clipped_action * MALLET_SPEED

        # Scripted opponent for training unless a user action is given
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

        # Moves both mallets
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

        # Hits first, then puck movement + goals
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

        info = {
            "goal": goal,
            "robot_hit": robot_hit,
            "user_hit": user_hit,
            "reward_parts": reward_parts,
            "step_count": self.step_count,
        }

        return self.observation(), reward, terminated, truncated, info

    # Draws everything
    def render(self, surface, font):
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

    # Nothing to close yet
    def close(self):
        pass



# Draws the table only
def draw_table(surface):
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


# Mallet chases the mouse, slows down when it's close so it doesn't jitter
def mouse_action(position):
    if not pygame.mouse.get_focused():
        return pygame.Vector2()

    action = (pygame.Vector2(pygame.mouse.get_pos()) - position) / 30

    if action.length() > 1:
        action.scale_to_length(1)

    return action


# Prints how the round ended + the reward total with each part
def print_round_summary(info, round_parts):
    outcome = {-1: "robot scored", 1: "robot conceded", 0: "time ran out"}[info["goal"]]
    print(f"round over ({outcome}): {sum(round_parts.values()):+.3f}", {n: round(v, 3) for n, v in round_parts.items()})


# You control blue vs the scripted opponent, no AI at all
def reward_test(keyboard=False):
    pygame.init()
    screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
    pygame.display.set_caption("Air Hockey reward test")
    clock = pygame.time.Clock()
    font = pygame.font.Font(None, 29)
    environment = AirHockeyEnv()
    environment.reset()
    recent_parts = deque(maxlen=50)
    round_parts = {}
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
                    round_parts = {}

        if keyboard:
            keys = pygame.key.get_pressed()
            robot_action = pygame.Vector2(
                int(keys[pygame.K_d] or keys[pygame.K_RIGHT]) - int(keys[pygame.K_a] or keys[pygame.K_LEFT]),
                int(keys[pygame.K_s] or keys[pygame.K_DOWN]) - int(keys[pygame.K_w] or keys[pygame.K_UP]),
            )
        else:
            robot_action = mouse_action(environment.robot_position)

        _, reward, terminated, truncated, info = environment.step(robot_action)

        for name, value in info["reward_parts"].items():
            round_parts[name] = round_parts.get(name, 0) + value

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
        step_text = font.render(f"you: ({robot_action.x:+.2f}, {robot_action.y:+.2f})  step={reward:+.3f}  round={sum(round_parts.values()):+.2f}", True, TEXT_COLOR)
        controls = font.render(f"Reward test: {'WASD or arrows' if keyboard else 'mouse'}   Space: reset   Esc: quit", True, TEXT_COLOR)
        screen.blit(total_text, (GOAL_LEFT, 12))
        screen.blit(step_text, (TABLE_RECT.left, WINDOW_HEIGHT - 55))
        screen.blit(controls, (TABLE_RECT.left, WINDOW_HEIGHT - 29))
        pygame.display.flip()

        if terminated or truncated:
            print_round_summary(info, round_parts)
            round_parts = {}
            environment.reset()

    environment.close()
    pygame.quit()
    return 0



# Visual demo (random policy, basic defender, or manual arrows)
def main():
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
    parser.add_argument(
        "--view_model",
        nargs="?",
        const="ppo_policy.pt",
        default=None,
        help="Watch a saved policy (default ppo_policy.pt) play as the blue robot. No training.",
    )
    parser.add_argument("--keyboard", action="store_true", help="Use WASD instead of the mouse for the mallet you control")
    args = parser.parse_args()
    if args.test_rewards:
        return reward_test(args.keyboard)

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
    round_parts = {}

    # Loads the saved model when viewing
    viewing = args.view_model is not None
    if viewing:
        policy.load_state_dict(torch.load(args.view_model))

    # Modes: random policy, basic defender, or manual arrows
    control_mode = "untrained_actor"
    running = True

    while running:
        clock.tick(FPS)

        # Window + mode keys
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_SPACE:
                    observation = environment.reset()
                    round_parts = {}
                elif event.key == pygame.K_n:
                    control_mode = (
                        "basic_defence"
                        if control_mode == "untrained_actor"
                        else "untrained_actor"
                    )
                elif event.key == pygame.K_m:
                    control_mode = "manual"

        # Red player follows the mouse (or wasd with --keyboard)
        keys = pygame.key.get_pressed()
        if args.keyboard:
            user_action = pygame.Vector2(
                int(keys[pygame.K_d]) - int(keys[pygame.K_a]),
                int(keys[pygame.K_s]) - int(keys[pygame.K_w]),
            )
        else:
            user_action = mouse_action(environment.user_position)

        # Picks what controls the blue robot
        if control_mode == "untrained_actor":
            with torch.no_grad():
                policy_input = torch.tensor(observation, dtype=torch.float32)
                _, policy_action, _, _ = policy.act(policy_input, explore=not viewing)

            robot_action = pygame.Vector2(policy_action.tolist())
            control_name = f"trained PPO ({args.view_model})" if viewing else "untrained PPO (random exploration)"
        elif control_mode == "basic_defence":
            robot_action = simple_defence_action(environment)
            control_name = "basic defender"
        else:
            robot_action = pygame.Vector2(
                int(keys[pygame.K_RIGHT]) - int(keys[pygame.K_LEFT]),
                int(keys[pygame.K_DOWN]) - int(keys[pygame.K_UP]),
            )
            control_name = "arrow-key robot"

        observation, reward, terminated, truncated, info = environment.step(
            robot_action,
            user_action=user_action,
        )

        for name, value in info["reward_parts"].items():
            round_parts[name] = round_parts.get(name, 0) + value

        environment.render(screen, font)
        command_text = font.render(
            f"{control_name}: ({robot_action.x:+.2f}, {robot_action.y:+.2f})  reward={reward:+.3f}",
            True,
            TEXT_COLOR,
        )
        controls = font.render(
            f"User: {'WASD' if args.keyboard else 'mouse'}   N: actor/defender   M: manual arrows   Space: reset",
            True,
            TEXT_COLOR,
        )
        screen.blit(command_text, (TABLE_RECT.left, WINDOW_HEIGHT - 55))
        screen.blit(controls, (TABLE_RECT.left, WINDOW_HEIGHT - 29))
        round_text = font.render(f"round reward: {sum(round_parts.values()):+.3f}", True, TEXT_COLOR)
        screen.blit(round_text, (GOAL_LEFT, 12))
        pygame.display.flip()

        if terminated or truncated:
            print_round_summary(info, round_parts)
            round_parts = {}
            observation = environment.reset()

    environment.close()
    pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
