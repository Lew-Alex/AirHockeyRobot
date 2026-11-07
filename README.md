# Air Hockey Robot

A robotic air-hockey table. A camera tracks the puck, a policy trained in
simulation decides where the mallet should go, and an ESP32 drives two brushed
DC motors through off-board motor drivers.

This is a personal project in progress. The status table below separates what
exists in this repository from what is only planned.

## Status

| Area | Status |
|---|---|
| Puck tracker (webcam, HSV yellow mask) | Prototype works on a webcam. No table calibration, filtering or bounce handling yet. |
| Camera latency test (OpenCV) | Script exists. Results are not recorded in this repo. |
| iPhone 120 fps camera test app | Source written (`src/iphone_camera_test`), **not yet compiled or run**: Xcode is not installed on the development Mac. |
| Simulation (Pygame) | Physics, scripted opponent and reward shaping exist. |
| PPO training | Actor and critic exist. The trainer collects a short rollout only. GAE, the PPO update and the training loop are not written. |
| Breakout PCB (ESP32 DevKitC V4) | Designed and passes Prometheus checks and KiCad DRC. **Not ordered, assembled or tested.** |
| Motor drivers, power supply | Candidates only. Nothing is decided (see `docs/hardware.md`). |
| ESP32 firmware | Not started. |
| ROS 2 integration | Not started. |

## Repository layout

```text
.
├── README.md
├── CLAUDE.md                      Project notes for AI coding assistants
├── docs/                          Architecture, hardware, PCB, perception, training plan
├── .claude/skills/                Project skills (PCB build, PPO training, iPhone app)
└── src/
    ├── AI_SIm/                    Pygame simulation and PPO code
    ├── perception/
    │   ├── prototype/             Webcam yellow-puck tracker
    │   └── input_testing/         Camera latency test script
    ├── test_pcb/                  Breakout PCB (Prometheus) and fabrication outputs
    └── iphone_camera_test/        iOS app to test 120 fps at a fixed shutter speed
```

## System overview

```text
camera ──> Mac ──(USB serial)──> ESP32 ──PWM/DIR──> motor drivers ──> 2 × 775 motors
 (puck)   tracking, filter,        │                     ^
          policy                   └── encoders, limit switches, e-stop sense
```

The Mac is meant to run perception and the trained policy. The ESP32 handles the
low-level motor interface through the breakout PCB. See `docs/architecture.md`.

## Quick start

Run each command from the folder named in front of it.

**Puck tracker** (`src/perception/prototype`)

```bash
python3 -m venv .venv && source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 puck_tracker.py                 # add --camera 1 if the wrong camera opens
python3 -m unittest discover -s tests
```

**Camera latency test** (repository root, using the tracker's environment)

```bash
src/perception/prototype/.venv/bin/python src/perception/input_testing/camera_latency.py
```

**Simulation** (`src/AI_SIm`, needs `pip install -r requirements.txt`)

```bash
python3 simulation.py                   # Pygame demo: N switches mode, M is manual, Space resets
python3 ppo_trainer.py                  # short rollout, prints rewards and advantages
```

Torch 2.0.x prints a "Failed to initialize NumPy" warning when NumPy 2 is installed.
It is harmless here; upgrade torch or use `numpy<2` to remove it.

**PCB** (`src/test_pcb`). Prometheus needs Java 17+; FreeRouting 2.0.1 needs
Java 21. If only Java 17 is installed, point `PROMETHEUS_JAVA` at a Java 21
runtime first.

```bash
prometheus board.py out/ --spec req.json --json
python3 tools/verify_nets.py            # checks the generated netlists against board.py
```

**iPhone app** (`src/iphone_camera_test`): see its README. It needs Xcode.

## Documentation

- `docs/architecture.md`: components and data flow
- `docs/hardware.md`: parts in hand, candidates and open decisions
- `docs/pcb.md`: connector and pin map, assembly and bring-up checklist
- `docs/perception.md`: camera plan, filtering and what the policy receives
- `docs/training-plan.md`: PPO status and the remaining steps
