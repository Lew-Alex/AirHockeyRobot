# PPO training plan

The PPO code is written by hand to learn the algorithm. This file records what is
done and what is left. See `.claude/skills/ppo-training/SKILL.md` for the interface
rules.

## Done

- `AirHockeyEnv` in `simulation.py`: physics (drag, wall bounces, mallet
  collisions), a scripted opponent, noisy observations, reward shaping with logged
  `reward_parts`, and `reset()` / `step()` returning
  `(obs, reward, terminated, truncated, info)`.
- `policy.py`: `Actor` (mean of a 2D Normal with learned log standard deviation,
  tanh output), `Critic`, and `ActorCritic.act()` returning
  `(raw_action, action, log_prob, value)`.
- `ppo_trainer.py`: a 20-step rollout that stores states, raw actions, log-probs,
  values and rewards under `torch.no_grad()`.

## Left, in order

1. Store `done`, `terminated` and `next_observation`.
2. Ratio sanity check: recomputed log-probs must equal the stored ones (ratio 1.0).
3. GAE with bootstrapping. Only `terminated` zeroes the bootstrap, not
   `truncated`. About gamma 0.99 and lambda 0.95. (The current `GAMMA = 0.9` looks
   only about 10 steps ahead, too short to connect a hit to a goal.)
4. Clipped actor loss, value loss, entropy bonus, normalized advantages, minibatch
   epochs, gradient clipping.
5. Outer loop with 2048-step rollouts, checkpoints, logging of reward, episode
   length, goal and save rates, and losses.
6. Evaluation with `explore=False` against the scripted opponent, and a Pygame view
   of the trained policy.
7. Tidy-ups: use `environment` not `enviorment`, replace `import *`, add seeds and
   a `__main__` guard.

## Things to check

- `AirHockeyEnv` defaults to `dt = 1/60`, while the demo ticks at 120 FPS.
- The observation noise model should match the real filter pipeline (see
  `perception.md`), and the simulator should include camera latency.
- Reward shaping should not outweigh the goal reward. Inspect `reward_parts`.
- The simulator uses pixel units. Define real table units and mallet limits before
  deploying.

## Later

Self-play, only after the policy beats a scripted opponent reliably. One policy can
learn both attack and defence if the observation, reward and training scenarios
include both.
