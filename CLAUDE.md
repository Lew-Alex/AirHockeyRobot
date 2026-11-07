# Air Hockey Robot: project notes for AI coding assistants

Read `README.md` first for the layout and the status of each part, then the
relevant file in `docs/`. Project skills are in `.claude/skills/`.

## Working rules for this project

- The owner is a first-year mechatronics student learning this stack. Explain the
  reasoning, not just the steps, and break large tasks into concrete next steps.
- Keep a clear line between what is **implemented**, what is **proposed**, and what
  is **decided**. Parts, designs and tests suggested in conversation are candidates,
  not decisions or achievements. State what you actually ran and what you did not.
- Make targeted edits that keep the existing style and naming. Do not turn a small
  request into a rewrite. The PPO code is hand-written on purpose.
- Do not trust a green check alone. For the PCB, run `src/test_pcb/tools/verify_nets.py`
  after every rebuild.
- Do not commit, push or order anything unless asked. Commits are authored by the
  owner.

## Layout

- `src/AI_SIm`: Pygame simulation and PPO code (skill: `ppo-training`)
- `src/perception`: webcam puck tracker and camera latency test
- `src/test_pcb`: ESP32 breakout PCB in Prometheus (skill: `pcb-build`)
- `src/iphone_camera_test`: iOS 120 fps capture test app (needs Xcode)
- `docs/`: architecture, hardware, PCB, perception, training plan

## Environment notes

- macOS with Python 3.11. The tracker has its own virtual environment in
  `src/perception/prototype/.venv`.
- Prometheus needs `PROMETHEUS_JAVA` pointing at a Java 21 runtime for FreeRouting
  2.0.1 (see the `pcb-build` skill).
- Xcode may not be installed. Without it the iOS app cannot be compiled here.
