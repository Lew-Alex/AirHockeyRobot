---
name: ppo-training
description: Work on the hand-written PPO trainer and Pygame simulation in src/AI_SIm. Use when editing ppo_trainer.py, policy.py or simulation.py, or when asked how the rollout, advantages, PPO update or sim-to-real pieces should work.
---

# PPO training in src/AI_SIm

The user is writing PPO by hand to learn it. Review and explain before rewriting,
keep their naming and structure, and make targeted edits. Do not turn a small
request into a rewrite.

## Interfaces (keep these consistent)

- **Observation (8 values, normalized):** puck x, y, vx, vy, then robot x, y, vx, vy.
  `AirHockeyEnv.reset()` and `.step()` return it as a tuple.
- **Action (2 values, in [-1, 1]):** robot velocity command. The sim scales it by
  `MALLET_SPEED`.
- **`ActorCritic.act(obs, explore=True)` returns four values:**
  `(raw_action, action, log_prob, value)`. The log-probability belongs to
  `raw_action`, so **store `raw_action` in the rollout** and pass the clamped
  `action` to `env.step()`. Storing the clamped action makes the PPO ratio start
  away from 1.
- `AirHockeyEnv.step()` returns `(obs, reward, terminated, truncated, info)`.
  `terminated` is a goal. `truncated` is the time limit.
- Every caller of `act()` must unpack four values (the trainer and the demo in
  `simulation.py`).

## Current state

The trainer collects a 20-step rollout and prints advantages. Still to write, in
order:

1. Store `done`, `terminated` and `next_observation` in the buffer.
2. Sanity check: recompute log-probs for the stored states and raw actions. The
   ratio against the stored log-probs must be 1.0 everywhere.
3. GAE (about gamma 0.99, lambda 0.95). Bootstrap from the critic's value of the
   last next state. Zero the bootstrap only for `terminated`, never for
   `truncated`. Returns are advantages plus values.
4. Clipped actor loss (epsilon about 0.2), value loss against the returns, entropy
   bonus, normalized advantages, minibatch epochs, gradient clipping.
5. Outer training loop, checkpoint save and load, logging (mean reward, episode
   length, goal and save rates, losses), a deterministic evaluation run with
   `explore=False`.

Collect rollouts under `torch.no_grad()` and detach everything stored for the
update.

## Things to check rather than assume

- `AirHockeyEnv` defaults to `dt = 1/60`, while the Pygame demo ticks at
  `FPS = 120`, so the demo may run the simulation faster than real time.
- `get_observation` adds noise straight to the true state. For sim-to-real, the
  observation should come from the same filter and latency as the real pipeline
  (see `docs/perception.md`).
- Reward shaping must not outweigh the goal reward. Log `info["reward_parts"]`.

## Running

```bash
cd src/AI_SIm
pip install -r requirements.txt
python3 simulation.py      # demo; N toggles policy/defender, M manual, Space resets
python3 ppo_trainer.py
```
