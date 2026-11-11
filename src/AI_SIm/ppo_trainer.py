from simulation import *
from policy import *


enviorment = AirHockeyEnv()

policy = ActorCritic()

# --resume loads the saved policy so training keeps going from there
import argparse
import os
parser = argparse.ArgumentParser()
parser.add_argument("--out", default="ppo_policy.pt", help="Where the trained policy is saved (checkpoints go in checkpoints/<name>/)")
parser.add_argument("--resume", nargs="?", const="ppo_policy.pt", default=None, help="Continue training from a saved policy (default ppo_policy.pt)")

# Hyperparameters, each one works like --updates=1000 or --UPDATES=1000
for name, default in [("updates", 1000), ("rollout_steps", 2048), ("epochs", 10), ("minibatch_size", 256), ("gamma", 0.99), ("lambda", 0.95), ("lr", 3e-4), ("clip", 0.2), ("value_coef", 0.5), ("entropy_coef", 0.0), ("max_grad_norm", 0.5), ("action_repeat", ACTION_REPEAT), ("save_every", 100)]:
    parser.add_argument(f"--{name}", f"--{name.upper()}", type=type(default), default=default)

args = parser.parse_args()
print("settings:", vars(args))

if args.resume:
    policy.load_state_dict(torch.load(args.resume))
    print("resumed from", args.resume)


GAMMA = args.gamma
LAMBDA = getattr(args, "lambda")
NUM_UPDATES = args.updates
ROLLOUT_STEPS = args.rollout_steps
EPOCHS = args.epochs
MINIBATCH_SIZE = args.minibatch_size

# Obvs = puck_x, puck_y, puck_vx, puck_vy, robot_x, robot_y, robot_vx, robot_vy
# Act = action, log_probability, critic_value
# Sample test or wtv


optimizer = torch.optim.Adam(policy.parameters(), lr=args.lr)
observation = enviorment.reset()

for update in range(NUM_UPDATES):
    total_reward = 0
    reward_parts_total = {}
    critic_values = []
    advantages = [] 
    rewards = [] # Rewards from each step
    states = []
    actions = []
    log_probs = []
    dones = []
    terminateds = []
    next_states = []



    for i in range(ROLLOUT_STEPS): # 20 steps of training for now

        policy_observation = torch.Tensor(observation)
        states.append(observation)


        # Computs policy(gets action, critic value, etc)
        with torch.no_grad():
            raw_action, action, log_probability, critic_value = policy.act(policy_observation)

        actions.append(raw_action)
        log_probs.append(log_probability)


        # Performs the step, the same action is held for action_repeat sim steps and the rewards add up
        reward = 0
        for _ in range(args.action_repeat):
            next_observation, step_reward, terminated, truncated, info = enviorment.step(action)
            reward += step_reward
            for name, value in info["reward_parts"].items():
                reward_parts_total[name] = reward_parts_total.get(name, 0) + value
            if terminated or truncated:
                break

        # Does stuff for next step
        done = terminated or truncated
        dones.append(done)
        terminateds.append(terminated)
        next_states.append(next_observation)



        critic_values.append(critic_value)
        rewards.append(reward)

        total_reward += reward

        if terminated or truncated:
            observation = enviorment.reset()
        else:
            observation = next_observation


    # For now this just checks the log probabilityes compared to the old ones
    with torch.no_grad():
        new_log_probs, _, _ = policy.evaluate(
            torch.tensor(states, dtype=torch.float32), torch.stack(actions)
        )

    ratio = torch.exp(new_log_probs - torch.stack(log_probs))
    print("ratio min/max:", ratio.min().item(), ratio.max().item())
    assert torch.allclose(ratio, torch.ones_like(ratio), atol=1e-3), "ratio is not 1: log-probs do not match"


    # Checks what the critic thinks of the next step given the next
    with torch.no_grad():
        next_values = policy.critic(torch.tensor(next_states, dtype=torch.float32))
    # This is what the critic thought of each next_state

    values = torch.stack(critic_values)
    reward_tensor = torch.tensor(rewards, dtype=torch.float32)
    terminated_tensor = torch.tensor(terminateds, dtype=torch.float32)
    done_tensor = torch.tensor(dones, dtype=torch.float32)

    deltas = reward_tensor + GAMMA * next_values * (1 - terminated_tensor) - values

    advantages = torch.zeros(ROLLOUT_STEPS)
    last_advantage = 0
    for t in reversed(range(ROLLOUT_STEPS)):
        last_advantage = deltas[t] + GAMMA * LAMBDA * (1 - done_tensor[t]) * last_advantage
        advantages[t] = last_advantage

    returns = advantages + values



    old_log_probs = torch.stack(log_probs)
    states_tensor = torch.tensor(states, dtype=torch.float32)
    actions_tensor = torch.stack(actions)
    normalized_advantages = (advantages - advantages.mean()) / (advantages.std() + 1e-8)

    for epoch in range(EPOCHS):
        shuffled = torch.randperm(ROLLOUT_STEPS)
        for start in range(0, ROLLOUT_STEPS, MINIBATCH_SIZE):
            idx = shuffled[start:start + MINIBATCH_SIZE]

            # Critic loss
            new_log_probs, entropy, new_values = policy.evaluate(states_tensor[idx], actions_tensor[idx])
            critic_loss = ((new_values - returns[idx]) ** 2).mean()

            # Actor loss
            ratio = torch.exp(new_log_probs - old_log_probs[idx])
            unclipped = ratio * normalized_advantages[idx]
            clipped = torch.clamp(ratio, 1 - args.clip, 1 + args.clip) * normalized_advantages[idx]
            actor_loss = -torch.min(unclipped, clipped).mean()

            # Calculates total loss + entropy(for exploration)
            entropy_loss = entropy.mean()
            total_loss = actor_loss + args.value_coef * critic_loss - args.entropy_coef * entropy_loss

            # Now actually calc grad + adam optimizer
            optimizer.zero_grad() # Resets previous grads
            total_loss.backward()
            torch.nn.utils.clip_grad_norm_(policy.parameters(), args.max_grad_norm)
            optimizer.step()

    # std is how random each action is (x,y), it should not collapse to 0
    std = policy.actor.log_standard_deviation.exp().clamp(min=MIN_STANDARD_DEVIATION).tolist()
    print(update, total_reward, actor_loss.item(), critic_loss.item(), f"std={std[0]:.3f},{std[1]:.3f}", {k: round(v, 2) for k, v in reward_parts_total.items()})

    # Saves a copy every save_every updates so a good one can be reloaded later
    if (update + 1) % args.save_every == 0:
        checkpoint_folder = os.path.join("checkpoints", os.path.splitext(os.path.basename(args.out))[0])
        os.makedirs(checkpoint_folder, exist_ok=True)
        torch.save(policy.state_dict(), os.path.join(checkpoint_folder, f"{update + 1}.pt"))

torch.save(policy.state_dict(), args.out)
