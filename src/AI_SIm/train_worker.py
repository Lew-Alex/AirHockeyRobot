"""Train the defense or offense worker with the unchanged ppo_trainer.py.

    python3 train_worker.py defense     # saves defense_policy.pt
    python3 train_worker.py offense     # saves offense_policy.pt

ppo_trainer.py always builds AirHockeyEnv() (the full game), and it is left as it is. This file
swaps in the right scenario first, then runs the trainer as if you had typed
`python3 ppo_trainer.py`. Any other flag goes to the trainer, for example:

    python3 train_worker.py defense --updates 300 --out my_defense.pt
"""

import os
import runpy
import sys

import simulation

# What each worker trains on. Offense uses a different opponent style every round
WORKERS = {
    "defense": {"mode": "defense"},
    "offense": {"mode": "offense", "opponent": "mixed"},
}

if len(sys.argv) < 2 or sys.argv[1] not in WORKERS:
    sys.exit(__doc__)

name = sys.argv[1]
trainer_flags = sys.argv[2:]
if "--out" not in trainer_flags:
    trainer_flags += ["--out", f"{name}_policy.pt"]

real_environment = simulation.AirHockeyEnv


def scenario_environment(*args, **kwargs):
    settings = {**WORKERS[name], **kwargs}
    print(f"training the {name} worker: AirHockeyEnv({settings})", flush=True)
    return real_environment(*args, **settings)


# ppo_trainer.py does `from simulation import *`, which picks up this replacement
simulation.AirHockeyEnv = scenario_environment

sys.argv = ["ppo_trainer.py"] + trainer_flags
runpy.run_path(os.path.join(os.path.dirname(os.path.abspath(__file__)), "ppo_trainer.py"), run_name="__main__")
