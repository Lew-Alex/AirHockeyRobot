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


# Real world scale, sim table length (810 px) = real table length (54 in)
PIXELS_PER_METER = TABLE_RECT.height / (54 * 0.0254)


# Puck / mallet physics
PUCK_RADIUS              = 18
MALLET_RADIUS            = 30
PUCK_DRAG                = 32.0
PUCK_MAX_SPEED           = 500.0
PUCK_SPEED_SCALE         = 500.0   # puck speeds are divided by this for the observation and the hit reward
MALLET_SPEED             = 2.0 * PIXELS_PER_METER
MALLET_ACCELERATION      = 10.0 * PIXELS_PER_METER
MALLET_VELOCITY_NOISE    = 22.0
SCRIPTED_OPPONENT_SPEED  = 0.20
ACTION_REPEAT            = 4

# A puck slower than STALL_SPEED for STALL_STEPS steps (2 s) gets served again from the center
STALL_SPEED              = 20.0
STALL_STEPS              = 120


# Simulated perception error
OBSERVATION_POSITION_NOISE = 2.5
OBSERVATION_VELOCITY_NOISE = 12.0


# Puck prediction (the two lines it predicts for + the longest time it reports)
PREDICTION_TIME_CAP = 2.0
HOME_LINE_Y         = TABLE_RECT.top + 90
FRONT_LINE_Y        = TABLE_RECT.centery - MALLET_RADIUS
USER_GOAL_LINE_Y    = TABLE_RECT.bottom - PUCK_RADIUS


# PPO reward shaping
GOAL_REWARD             = 10.0
CONCEDED_GOAL_REWARD    = -10.0
APPROACH_REWARD         = 0.00125
HIT_DIRECTION_REWARD    = 0.20
HIT_BACKWARD_PENALTY    = -0.10
PUCK_BEHIND_PENALTY     = -0.001
SHOT_ON_GOAL_REWARD     = 1.50


# Training modes: "full" is the normal game (rewards above), "defense" and "offense" are scenarios for the two worker networks
MODES = ("full", "defense", "offense")
ROBOT_GOAL_LINE_Y = TABLE_RECT.top + PUCK_RADIUS

# Defense reward (goals are still +-10, the rest is small so it never outweighs them)
DEFENSE_SAVE_REWARD      = 1.0     # first touch of a puck that was heading at our goal
DEFENSE_CLEARED_REWARD   = 3.0     # puck sent past the center line after we touched it, ends the round
DEFENSE_STOPPED_REWARD   = 1.0     # puck came to rest on our half without a goal, ends the round
DEFENSE_BAD_HIT_PENALTY  = -1.0    # a touch that leaves the puck headed into our own goal
DEFENSE_ALIGN_REWARD     = 0.3     # per unit of table width closed between the mallet and where the puck will cross
DEFENSE_MAX_STEPS        = 600     # 10 s

# Offense reward
OFFENSE_SHOT_ON_GOAL_REWARD = 2.0
OFFENSE_SHOT_SPEED_REWARD   = 0.5  # times shot speed / PUCK_SPEED_SCALE, only for shots on goal
OFFENSE_OWN_GOAL_PENALTY    = -1.0 # a touch that leaves the puck headed into our own goal
OFFENSE_STALLED_PENALTY     = -1.0 # we touched it but it died on our half
OFFENSE_IDLE_PENALTY        = -1.0 # time ran out and we never touched the puck
OFFENSE_MAX_STEPS           = 900  # 15 s
OFFENSE_REWARDED_TOUCHES    = 2    # approach, hit direction and shot rewards only count for the first 2 touches of a round,
                                   # otherwise a long rally of shots on goal would earn more than scoring

# Opponent styles, speeds are fractions of the mallet's top speed (my picks, not measured)
OPPONENT_STYLES = ("passive", "wanderer", "chaser", "attacker", "idle", "mixed")
OPPONENT_SPEED = {"passive": SCRIPTED_OPPONENT_SPEED, "wanderer": 0.35, "chaser": 0.60, "attacker": 0.50}
MIXED_OPPONENTS = ("passive", "wanderer", "chaser", "attacker")
WANDER_STEPS = 60


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


# Defense scenario: the puck starts on the user's half and is shot at a point near the robot's goal
# Speed is picked relative to what it needs to even reach the goal (drag), so slow and fast shots both happen
def reset_defense_puck(rng):
    position = pygame.Vector2(
        rng.uniform(TABLE_RECT.left + 80, TABLE_RECT.right - 80),
        TABLE_RECT.centery + rng.uniform(60, 300),
    )
    target = pygame.Vector2(
        rng.uniform(GOAL_LEFT - 70, GOAL_RIGHT + 70),
        TABLE_RECT.top,
    )
    direction = target - position
    distance = direction.length()
    speed = min(PUCK_MAX_SPEED, math.sqrt(2 * PUCK_DRAG * distance) * rng.uniform(1.1, 2.4))
    direction.scale_to_length(speed)
    return position, direction


# Offense scenario: the puck is on the robot's half, still or drifting slowly
def reset_offense_puck(rng):
    position = pygame.Vector2(
        rng.uniform(TABLE_RECT.left + 70, TABLE_RECT.right - 70),
        rng.uniform(TABLE_RECT.top + 120, TABLE_RECT.centery - 70),
    )
    velocity = pygame.Vector2()

    if rng.random() < 0.5:
        angle = rng.uniform(0, 2 * math.pi)
        velocity.update(math.cos(angle), math.sin(angle))
        velocity.scale_to_length(rng.uniform(20, 120))

    return position, velocity


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



# Predicts where the puck crosses a horizontal line (y), counting drag + side wall bounces
# Gives back (x, seconds, arrives), if it never gets there it gives the puck's current x, the max time and False
def predict_puck_at_line(puck_x, puck_y, velocity_x, velocity_y, line_y):
    speed = math.hypot(velocity_x, velocity_y)

    # Not moving up or down so it never gets there
    if speed < 1e-6 or velocity_y == 0:
        return puck_x, PREDICTION_TIME_CAP, False

    # How far along its path it has to travel to reach the line
    distance = (line_y - puck_y) * speed / velocity_y

    # Moving away from the line, or drag stops it first (it can only go speed^2 / (2 * drag))
    if distance < 0 or distance > speed * speed / (2 * PUCK_DRAG):
        return puck_x, PREDICTION_TIME_CAP, False

    # Solves speed * t - drag * t^2 / 2 = distance for the smaller t
    arrival_time = (speed - math.sqrt(max(speed * speed - 2 * PUCK_DRAG * distance, 0.0))) / PUCK_DRAG

    # Unfolds x along the path, then folds it back in for the wall bounces
    predicted_x = reflect_x_at_table_walls(puck_x + velocity_x / speed * distance)

    return predicted_x, min(arrival_time, PREDICTION_TIME_CAP), True



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



# Hand-written manager that picks "defense" or "offense" from the 12-number observation
# Offense when the puck is on the robot's half and not coming at the robot's goal, defense otherwise
# The mode is held for a few decisions so it can't flicker (decisions are ACTION_REPEAT sim steps apart)
# Thresholds are my picks. Measured with basic stand-in workers it still flips about 13 times per round
# (the puck sits near the boundary), so treat it as a rough baseline and retune once both workers exist
class RuleManager:

    def __init__(self, hold_decisions=8, threat_speed=0.15):
        self.hold_decisions = hold_decisions
        self.threat_speed = threat_speed    # puck speed toward our goal (/ PUCK_SPEED_SCALE) that counts as a threat
        self.reset()

    def reset(self):
        self.mode = "defense"
        self.decisions_since_switch = self.hold_decisions

    def choose(self, observation):
        # observation[1] is the puck y (negative = robot half), [3] is the puck's vertical velocity / PUCK_SPEED_SCALE
        on_robot_half = observation[1] < 0
        coming_at_our_goal = observation[3] < -self.threat_speed
        wanted = "offense" if on_robot_half and not coming_at_our_goal else "defense"

        if wanted != self.mode and self.decisions_since_switch >= self.hold_decisions:
            self.mode = wanted
            self.decisions_since_switch = 0

        self.decisions_since_switch += 1
        return self.mode



# Training environment
# reset() gives the first observation
# step(action) takes a robot velocity [x, y] between -1 and 1 and gives back observation, reward, terminated, truncated, info
class AirHockeyEnv:

    # mode: "full" (normal game), "defense" (puck shot at our goal) or "offense" (puck still on our half)
    # opponent: how the red mallet plays, "mixed" picks a different style each round
    # max_steps: None uses the mode's default (1800 full, 600 defense, 900 offense)
    def __init__(self, dt=1 / 60, max_steps=None, add_observation_noise=True, seed=None, mode="full", opponent="passive"):
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        if opponent not in OPPONENT_STYLES:
            raise ValueError(f"opponent must be one of {OPPONENT_STYLES}")

        self.dt = dt
        self.mode = mode
        self.opponent = opponent
        self.max_steps = max_steps or {"full": 1_800, "defense": DEFENSE_MAX_STEPS, "offense": OFFENSE_MAX_STEPS}[mode]
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
        self.robot_was_hitting = False
        self.robot_touched = False
        self.rewarded_touches = 0
        self.stalled_steps = 0

        # Robot starts at the top, user at the bottom
        self.robot_position.update(TABLE_RECT.centerx, TABLE_RECT.top + 90)
        self.robot_velocity.update(0.0, 0.0)
        self.user_position.update(TABLE_RECT.centerx, TABLE_RECT.bottom - 90)
        self.user_velocity.update(0.0, 0.0)

        # The opponent's style for this round (defense rounds have a still opponent, the shot is the opponent)
        if self.mode == "defense":
            self.opponent_style = "idle"
        elif self.opponent == "mixed":
            self.opponent_style = self.rng.choice(MIXED_OPPONENTS)
        else:
            self.opponent_style = self.opponent
        self.wander_target = pygame.Vector2(self.user_position)
        self.wander_steps_left = 0

        if self.mode == "defense":
            self.puck_position, self.puck_velocity = reset_defense_puck(self.rng)
        elif self.mode == "offense":
            self.puck_position, self.puck_velocity = reset_offense_puck(self.rng)
        else:
            self.puck_position, self.puck_velocity = reset_puck(rng=self.rng)

        # The scenarios also start the robot somewhere random half the time so it learns from any position
        if self.mode != "full" and self.rng.random() < 0.5:
            self.robot_position.update(
                self.rng.uniform(TABLE_RECT.left + MALLET_RADIUS, TABLE_RECT.right - MALLET_RADIUS),
                self.rng.uniform(TABLE_RECT.top + MALLET_RADIUS, TABLE_RECT.centery - MALLET_RADIUS),
            )
            if self.robot_position.distance_to(self.puck_position) < PUCK_RADIUS + MALLET_RADIUS + 10:
                self.robot_position.update(TABLE_RECT.centerx, TABLE_RECT.top + 90)

        self.alignment_error = self._alignment_error()

        return self.observation()

    # The 12 numbers the policy sees (normalized + noisy), the last 4 are the predicted puck x + time at the 2 lines
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

        base = (
            (raw[0] - TABLE_RECT.centerx) / half_width,
            (raw[1] - TABLE_RECT.centery) / half_height,
            raw[2] / PUCK_SPEED_SCALE,
            raw[3] / PUCK_SPEED_SCALE,
            (raw[4] - TABLE_RECT.centerx) / half_width,
            (raw[5] - TABLE_RECT.centery) / half_height,
            raw[6] / MALLET_SPEED,
            raw[7] / MALLET_SPEED,
        )

        # Predicted puck x + arrival time at the home line and the front line (from the same noisy numbers)
        predicted = []
        for line_y in (HOME_LINE_Y, FRONT_LINE_Y):
            predicted_x, predicted_time, _ = predict_puck_at_line(raw[0], raw[1], raw[2], raw[3], line_y)
            predicted.append((predicted_x - TABLE_RECT.centerx) / half_width)
            predicted.append(predicted_time / PREDICTION_TIME_CAP)

        return base + tuple(predicted)

    # Moves the red mallet toward a target at a fraction of top speed
    def _opponent_move_to(self, target, speed_fraction):
        direction = target - self.user_position

        if direction.length() < 5:
            return pygame.Vector2()

        return direction.normalize() * speed_fraction

    # Opponent for this round, picked by style
    def scripted_user_action(self):
        style = self.opponent_style
        home = pygame.Vector2(TABLE_RECT.centerx, TABLE_RECT.bottom - 90)
        puck_on_user_half = self.puck_position.y > TABLE_RECT.centery

        if style == "idle":
            return pygame.Vector2()

        if style == "passive":
            return self._passive_user_action()

        if style == "wanderer":
            # Drifts to random spots on its half and ignores the puck
            self.wander_steps_left -= 1
            if self.wander_steps_left <= 0:
                self.wander_target = pygame.Vector2(
                    self.rng.uniform(TABLE_RECT.left + MALLET_RADIUS, TABLE_RECT.right - MALLET_RADIUS),
                    self.rng.uniform(TABLE_RECT.centery + MALLET_RADIUS, TABLE_RECT.bottom - MALLET_RADIUS),
                )
                self.wander_steps_left = WANDER_STEPS
            return self._opponent_move_to(self.wander_target, OPPONENT_SPEED[style])

        if style == "chaser":
            # Goes straight at the puck whenever it is on its half
            return self._opponent_move_to(self.puck_position if puck_on_user_half else home, OPPONENT_SPEED[style])

        # attacker: gets behind the puck, then drives through it toward the robot's goal
        if not puck_on_user_half:
            return self._opponent_move_to(home, OPPONENT_SPEED[style])

        goal_center = pygame.Vector2(TABLE_RECT.centerx, TABLE_RECT.top)
        shot_direction = goal_center - self.puck_position
        shot_direction = shot_direction.normalize() if shot_direction.length() > 0 else pygame.Vector2(0, -1)
        behind_offset = self.user_position - self.puck_position
        along = behind_offset.dot(shot_direction)                          # negative = behind the puck
        sideways = abs(behind_offset.dot(pygame.Vector2(-shot_direction.y, shot_direction.x)))

        if along < -(PUCK_RADIUS + MALLET_RADIUS) * 0.8 and sideways < 35:
            target = self.puck_position
        else:
            target = self.puck_position - shot_direction * (PUCK_RADIUS + MALLET_RADIUS + 50)
        return self._opponent_move_to(target, OPPONENT_SPEED[style])

    # The original basic opponent, defends its goal and follows the puck
    def _passive_user_action(self):
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

        return direction.normalize() * SCRIPTED_OPPONENT_SPEED

    # Reward for one step, goals are way bigger than the shaping stuff
    def _reward(self, goal, robot_hit, puck_y_before_step, robot_dy, puck_distance_closed, action):
        parts = {}

        if goal == -1:
            parts["goal"] = GOAL_REWARD
        elif goal == 1:
            parts["goal"] = CONCEDED_GOAL_REWARD
        else:
            # First step of a hit only
            if robot_hit and not self.robot_was_hitting:
                # Faster toward the other goal = more reward, backwards costs a little
                if self.puck_velocity.y > 0:
                    parts["hit_direction"] = HIT_DIRECTION_REWARD * self.puck_velocity.y / PUCK_SPEED_SCALE
                else:
                    parts["hit_direction"] = HIT_BACKWARD_PENALTY

                # If the puck is now headed into the user's goal that's a shot on goal
                goal_x, _, arrives = predict_puck_at_line(self.puck_position.x, self.puck_position.y, self.puck_velocity.x, self.puck_velocity.y, USER_GOAL_LINE_Y)
                if arrives and GOAL_LEFT < goal_x < GOAL_RIGHT:
                    parts["shot_on_goal"] = SHOT_ON_GOAL_REWARD

            # Puck on our half, getting closer to it is rewarded
            if puck_y_before_step < TABLE_RECT.centery:
                parts["approach"] = APPROACH_REWARD * puck_distance_closed

            # Puck behind the mallet (toward the robot's own goal) costs a little every step
            if self.puck_position.y <= self.robot_position.y:
                parts["puck_behind"] = PUCK_BEHIND_PENALTY

        return sum(parts.values()), parts

    # How far (in table widths) the mallet is from where an incoming puck will cross the home line
    # None when the puck is not coming at the robot's goal
    def _alignment_error(self):
        if self.puck_velocity.y >= -1:
            return None

        predicted_x, _, arrives = predict_puck_at_line(self.puck_position.x, self.puck_position.y, self.puck_velocity.x, self.puck_velocity.y, HOME_LINE_Y)
        if not arrives:
            return None

        return abs(self.robot_position.x - predicted_x) / TABLE_RECT.width

    # True when the puck is on course to enter the robot's own goal
    def _puck_heading_into_own_goal(self):
        goal_x, _, arrives = predict_puck_at_line(self.puck_position.x, self.puck_position.y, self.puck_velocity.x, self.puck_velocity.y, ROBOT_GOAL_LINE_Y)
        return arrives and GOAL_LEFT < goal_x < GOAL_RIGHT

    # Defense network: keep the puck out, then send it away
    # hit_started = first step of a robot touch, puck_velocity_before = the puck's velocity before that touch
    def _reward_defense(self, outcome, hit_started, puck_velocity_before, alignment_before, alignment_after):
        parts = {}

        if outcome == "conceded":
            parts["goal"] = CONCEDED_GOAL_REWARD
        elif outcome == "scored":
            parts["goal"] = GOAL_REWARD

        if hit_started:
            if puck_velocity_before.y < -1:
                parts["save"] = DEFENSE_SAVE_REWARD
            if self._puck_heading_into_own_goal():
                parts["bad_hit"] = DEFENSE_BAD_HIT_PENALTY

        if outcome == "cleared":
            parts["cleared"] = DEFENSE_CLEARED_REWARD
        elif outcome == "stopped":
            parts["stopped"] = DEFENSE_STOPPED_REWARD

        # Getting in line with the incoming puck, counted as the change in error so it can't be farmed by standing still
        if alignment_before is not None and alignment_after is not None:
            parts["align"] = DEFENSE_ALIGN_REWARD * (alignment_before - alignment_after)

        return sum(parts.values()), parts

    # Offense network: touch the puck, aim it at the user's goal, score
    def _reward_offense(self, outcome, hit_started, puck_y_before_step, puck_distance_closed):
        parts = {}

        if outcome == "scored":
            parts["goal"] = GOAL_REWARD
        elif outcome == "conceded":
            parts["goal"] = CONCEDED_GOAL_REWARD

        still_rewarding = self.rewarded_touches < OFFENSE_REWARDED_TOUCHES

        if hit_started:
            # Faster toward the other goal = more reward (first touches only), backwards always costs a little
            if self.puck_velocity.y <= 0:
                parts["hit_direction"] = HIT_BACKWARD_PENALTY
            elif still_rewarding:
                parts["hit_direction"] = HIT_DIRECTION_REWARD * self.puck_velocity.y / PUCK_SPEED_SCALE

            goal_x, _, arrives = predict_puck_at_line(self.puck_position.x, self.puck_position.y, self.puck_velocity.x, self.puck_velocity.y, USER_GOAL_LINE_Y)
            if still_rewarding and arrives and GOAL_LEFT < goal_x < GOAL_RIGHT:
                parts["shot_on_goal"] = OFFENSE_SHOT_ON_GOAL_REWARD
                parts["shot_speed"] = OFFENSE_SHOT_SPEED_REWARD * min(self.puck_velocity.length() / PUCK_SPEED_SCALE, 1.0)

            if self._puck_heading_into_own_goal():
                parts["own_goal_risk"] = OFFENSE_OWN_GOAL_PENALTY

            self.rewarded_touches += 1

        # Getting to the puck while it is on our half (before the second touch)
        if still_rewarding and puck_y_before_step < TABLE_RECT.centery:
            parts["approach"] = APPROACH_REWARD * puck_distance_closed

        # Puck behind the mallet (toward the robot's own goal) costs a little every step
        if self.puck_position.y <= self.robot_position.y:
            parts["puck_behind"] = PUCK_BEHIND_PENALTY

        if outcome == "stalled" and self.puck_position.y < TABLE_RECT.centery:
            parts["stalled"] = OFFENSE_STALLED_PENALTY
        elif outcome == "timeout" and not self.robot_touched:
            parts["idle"] = OFFENSE_IDLE_PENALTY

        return sum(parts.values()), parts

    # How a scenario round ended: scored, conceded, cleared, stopped, stalled or none (still going)
    def _scenario_outcome(self, goal):
        if goal == -1:
            return "scored"
        if goal == 1:
            return "conceded"

        puck_on_robot_half = self.puck_position.y < TABLE_RECT.centery

        if self.mode == "defense":
            if self.robot_touched and not puck_on_robot_half and self.puck_velocity.y > 0:
                return "cleared"
            if self.stalled_steps >= STALL_STEPS:
                return "stopped" if puck_on_robot_half else "stalled"
        elif self.mode == "offense":
            # The puck starts still, so it only counts as stalled once we have touched it
            if self.robot_touched and self.stalled_steps >= STALL_STEPS:
                return "stalled"

        return "none"

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
        puck_velocity_before_step = self.puck_velocity.copy()
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
        puck_distance_closed = puck_distance_before_step - self.robot_position.distance_to(self.puck_position)
        hit_started = robot_hit and not self.robot_was_hitting

        if self.mode == "full":
            reward, reward_parts = self._reward(
                goal=goal,
                robot_hit=robot_hit,
                puck_y_before_step=puck_y_before_step,
                robot_dy=self.robot_position.y - robot_y_before_step,
                puck_distance_closed=puck_distance_closed,
                action=clipped_action,
            )
        self.robot_was_hitting = robot_hit

        if robot_hit:
            self.robot_touched = True

        # A puck that has nearly stopped for a while counts as stalled (in the scenarios a touch restarts the count)
        if self.puck_velocity.length() < STALL_SPEED and not (robot_hit and self.mode != "full"):
            self.stalled_steps += 1
        else:
            self.stalled_steps = 0

        # Full game: a stalled puck gets served again, otherwise nobody plays it
        if self.mode == "full":
            if self.stalled_steps >= STALL_STEPS and goal == 0:
                self.puck_position, self.puck_velocity = reset_puck(rng=self.rng)
                self.stalled_steps = 0

            outcome = {-1: "scored", 1: "conceded", 0: "none"}[goal]
            terminated = goal != 0
            truncated = self.step_count >= self.max_steps
        else:
            # Scenarios end on a goal, a clear, a stop, or the time limit, and use their own rewards
            outcome = self._scenario_outcome(goal)
            terminated = outcome != "none"
            truncated = self.step_count >= self.max_steps
            if truncated and not terminated:
                outcome = "timeout"

            alignment_before = self.alignment_error
            self.alignment_error = self._alignment_error()

            if self.mode == "defense":
                reward, reward_parts = self._reward_defense(outcome, hit_started, puck_velocity_before_step, alignment_before, self.alignment_error)
            else:
                reward, reward_parts = self._reward_offense(outcome, hit_started, puck_y_before_step, puck_distance_closed)

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
            "mode": self.mode,
            "outcome": outcome,
            "opponent": self.opponent_style,
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
            f"Robot {self.robot_score}   |   User {self.user_score}   [{self.mode}, {self.opponent_style}]",
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
    if info.get("outcome") in ("cleared", "stopped", "stalled", "timeout"):
        outcome = info["outcome"]
    print(f"round over ({outcome}): {sum(round_parts.values()):+.3f}", {n: round(v, 3) for n, v in round_parts.items()})


# You control blue vs the scripted opponent, no AI at all
def reward_test(keyboard=False, mode="full", opponent="passive"):
    pygame.init()
    screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
    pygame.display.set_caption("Air Hockey reward test")
    clock = pygame.time.Clock()
    font = pygame.font.Font(None, 29)
    environment = AirHockeyEnv(mode=mode, opponent=opponent)
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
    parser.add_argument("--mode", choices=MODES, default="full", help="full game, or the defense / offense training scenario")
    parser.add_argument("--opponent", choices=OPPONENT_STYLES, default="passive", help="How the red opponent plays (defense rounds always use a still one)")
    args = parser.parse_args()
    if args.test_rewards:
        return reward_test(args.keyboard, args.mode, args.opponent)

    import torch

    from policy import ActorCritic

    pygame.init()
    screen = pygame.display.set_mode((WINDOW_WIDTH, WINDOW_HEIGHT))
    pygame.display.set_caption("Air Hockey AI Simulation")
    clock = pygame.time.Clock()
    font = pygame.font.Font(None, 29)
    environment = AirHockeyEnv(mode=args.mode, opponent=args.opponent)
    observation = environment.reset()
    policy = ActorCritic()
    round_parts = {}
    held_action = None
    frames_held = 0

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
                    held_action = None
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
            # The policy only picks a new action every ACTION_REPEAT steps, same as in training
            if held_action is None or frames_held >= ACTION_REPEAT:
                with torch.no_grad():
                    policy_input = torch.tensor(observation, dtype=torch.float32)
                    _, policy_action, _, _ = policy.act(policy_input, explore=not viewing)
                held_action = pygame.Vector2(policy_action.tolist())
                frames_held = 0
            frames_held += 1

            robot_action = held_action
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
            held_action = None

    environment.close()
    pygame.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
