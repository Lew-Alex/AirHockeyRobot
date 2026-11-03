from simulation import *
from policy import *


enviorment = AirHockeyEnv()

policy = ActorCritic()



GAMMA = 0.9

# Obvs = puck_x, puck_y, puck_vx, puck_vy, robot_x, robot_y, robot_vx, robot_vy
# Act = action, log_probability, critic_value
# Sample test or wtv


total_reward = 0
critic_values = []
advantages = [] # Should be 20 array of advantages for each step
rewards = [] # Rewards from each step
states = []
actions = []
log_probs = []


observation = enviorment.reset()
for i in range(20): # 20 steps of training for now

    policy_observation = torch.Tensor(observation)
    states.append(observation)

    action, log_probability, critic_value = policy.act(policy_observation)

    actions.append(action)
    log_probs.append(log_probability)

    observation, reward, terminated, truncated, info = enviorment.step(action)

    critic_values.append(critic_value)
    rewards.append(reward)

    total_reward += reward

    



for i in range(20):
    advantages.append(0)
    for j in range(i, 20):
        advantages[i] += rewards[j] * pow(GAMMA, j - i)
    advantages[i] -= critic_values[i]

print(rewards, critic_values, advantages)

