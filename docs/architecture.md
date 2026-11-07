# Architecture

Status words used in these docs: **implemented** (exists in this repo and was
run), **written** (exists but not run on real hardware), **proposal** (an idea
discussed but not decided), **open** (needs a decision or a measurement).

## Components

| Component | Role | Status |
|---|---|---|
| Camera | Sees the table and puck | Webcam prototype implemented. iPhone 13 at 120 fps under investigation. |
| Mac | Perception, state estimation, policy, serial link to the ESP32 | Tracker prototype implemented. The rest is not started. |
| ESP32 (DevKitC V4) | Reads encoders, limit switches and e-stop sense, outputs PWM and DIR to the drivers | Pins assigned on the PCB. Firmware not started. |
| Breakout PCB | Connectors and signal conditioning between the ESP32 and everything else | Designed, checks pass, not built. |
| Motor drivers | Drive two brushed DC motors from 24 V | **Open.** Candidates in `hardware.md`. |
| Motors | Two 24 V brushed 775 motors with Hall encoders, moving the mallet through belts | Mechanics designed in Fusion 360. |
| Policy | PPO actor network trained in simulation | Actor and critic written. Training loop not written. |

## Data flow

```text
camera frames ──> puck detection ──> table coordinates ──> filter ──┐
                                                                    ├─> policy ──> velocity command
encoders (via ESP32) ───────────> mallet position and velocity ─────┘                    │
                                                                                          v
                          ESP32 <── serial ── Mac            motor drivers <── PWM + DIR ── ESP32
```

- **Puck detection:** HSV yellow mask on a marker, centroid in image pixels
  (implemented in `src/perception/prototype`).
- **Table coordinates:** image to table homography from ArUco markers at the
  table corners (proposal, not implemented).
- **Filter:** a Kalman-style filter that also handles wall bounces and
  compensates camera latency (proposal; see `perception.md`).
- **Policy input:** the same 8 values the simulator produces: puck x, y, vx, vy
  and mallet x, y, vx, vy, normalized (implemented in the sim).
- **Policy output:** two normalized velocity values in [-1, 1].
- **ESP32:** turns the velocity command into per-motor PWM and DIR. It also needs
  limit-switch homing, a watchdog and safe disable (not written).

## Interfaces that are not defined yet

- The serial protocol between the Mac and the ESP32 (message format, rate,
  watchdog behaviour).
- Real table dimensions and units. The simulator works in pixels in a 700 x 900
  window; the real robot needs SI units and measured speed limits.
- Which machine runs the policy. ROS 2 is primarily supported on Ubuntu and
  Windows, and macOS support is limited, so a Mac-hosted design should not
  depend on ROS 2.

## Safety

The motor supply is 24 V at tens of amps from a mains-powered supply. Any build
needs: a fuse between supply and drivers, a hardware e-stop that cuts the 24 V
(the PCB's e-stop input only lets the firmware know it was pressed), and a plan
for motor regeneration, which can trip a switching supply or raise the bus
voltage. See `hardware.md`.
