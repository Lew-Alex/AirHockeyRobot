# Model optimization and interactive course plan

## Scope and preservation

Keep `src/AI_SIm/simulation.py`, `policy.py`, and `ppo_trainer.py` unchanged.
Build the new implementation and reproducible evaluation under `src/AI_SIm/optimization_lab/`.
The interactive course must use actual findings/results and export working Python.
No saved model checkpoint was found in this checkout, including ignored files.
Existing training code implements PPO; older project training notes are stale.

## Work sequence

1. Audit actual observation, action, reward, exploration, actuator noise, braking and cadence.
2. Freeze original file hashes; define development and held-out seed/scenario suites.
3. Measure stationary/basic baselines, reachable defence, attack, and idle movement separately.
4. Optimize an explicit non-ML reference controller, then train/evaluate a separate learned policy.
   Never call a scripted controller a trained neural model. Report any unachieved targets.
5. Build an interactive course: existing architecture, diagnosis, metrics, control, rewards,
   training/validation, robustness, and deployment boundaries. Provide live experiments,
   editable source, reset/compare, saved learner progress and Python copy/download.
6. Validate code exports, benchmark provenance, honest score labels and original file hashes.

## Acceptance criteria

- Blocking means saves divided by specified inbound goal threats, with exclusions disclosed.
- Attack means clean contacts, shots on goal and goals measured independently of reward.
- Idle movement means mallet path length and action magnitude in explicitly nonthreatening states.
- Same engine, cadence, observation information and noise for fair baseline comparisons.
- Fixed development seeds and disjoint held-out seeds; failures/uncertainty remain visible.
- A 100% finite-suite result is not a guarantee against all future shots or a physical robot.
- The course exports complete executable code, not just pseudocode or a browser-only mock.
- No original PPO/simulator files or Android sources are changed by this work.
