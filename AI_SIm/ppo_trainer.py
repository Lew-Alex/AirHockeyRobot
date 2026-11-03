from simulation import *
from policy import *


enviorment = AirHockeyEnv()

policy = ActorCritic()



# Obvs = puck_x, puck_y, puck_vx, puck_vy, robot_x, robot_y, robot_vx, robot_vy
# Act = action, log_probability, value
# Sample test or wtv

observation = enviorment.reset()

action, log_probability, value = policy.act(observation)

observation, reward, terminated, truncated, info = enviorment.step(action)