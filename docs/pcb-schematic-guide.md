# Reading the breakout PCB schematic

A plain-English key to every wire (net) name on the schematic of `src/test_pcb`. The board is a
signal-only breakout: the ESP32 plugs into two sockets, and everything else (motor drivers,
encoders, switches) connects through the small connectors. The 24 V motor power never touches
this board.

Names written like `PWM1_MCU` are the wire labels you will see in KiCad. "GPIO" means one
numbered pin on the ESP32 (IO25 = GPIO 25).

## Power wires

| Wire | What it means |
|---|---|
| `GND` | Ground, the 0 V reference. Everything shares it. Also poured as copper on both board layers. |
| `V3` | 3.3 V from the ESP32. Powers the pull-up resistors and the spare header. |
| `V5` | 5 V from the ESP32 board (its USB supply). Only feeds the encoder jumper and the optional driver tap. |
| `ENCVCC` | The supply sent to the encoders. The jumper JP1 picks it: pins 1-2 = 3.3 V, pins 2-3 = 5 V. Use whatever your encoders need. |

## Motor control wires (one pair per motor)

The ESP32 pin goes through a 220 Ω resistor (protects the pin) to the connector. A 10 kΩ resistor
holds the signal at 0 V when the ESP32 is off or booting, so the motor can't twitch.

| Wire | What it means |
|---|---|
| `PWM1_MCU` / `PWM2_MCU` | Speed signal straight out of the ESP32 (GPIO25 for motor 1, GPIO27 for motor 2), before the resistor. |
| `PWM1` / `PWM2` | The same speed signal after the 220 Ω resistor, at the MOTOR1 / MOTOR2 connector. Fast on/off pulses: more "on" time means faster. |
| `DIR1_MCU` / `DIR2_MCU` | Direction signal straight out of the ESP32 (GPIO26 for motor 1, GPIO33 for motor 2). |
| `DIR1` / `DIR2` | The direction signal at the connector. High spins one way, low the other (depends on the driver). |

## Encoder wires (position sensing, one set per motor)

An encoder sends two pulse trains, A and B. Counting them gives motor position, and which one
comes first gives the direction.

| Wire | What it means |
|---|---|
| `E1A_RAW`, `E1B_RAW`, `E2A_RAW`, `E2B_RAW` | The encoder's pulse signal exactly as it arrives at the connector, with a 4.7 kΩ resistor pulling it up to 3.3 V. |
| `E1A`, `E1B`, `E2A`, `E2B` | The same signal after a 1 kΩ resistor and a 330 pF capacitor that smooth out electrical noise, then into the ESP32 (E1 on GPIO34 and 35, E2 on GPIO36 and 39). |

## Limit switch and e-stop wires

The switches are normally closed to ground. While the switch is fine, the signal reads low. If
it opens or the wire breaks, the pull-up makes it read high, so a broken wire is treated the same
as a pressed switch (fail-safe).

| Wire | What it means |
|---|---|
| `LIM1_RAW` ... `LIM4_RAW`, `ESTOP_RAW` | The switch signal at its connector, pulled up to 3.3 V through 10 kΩ. |
| `LIM1` ... `LIM4`, `ESTOP` | The same signal after a 1 kΩ resistor and 100 nF capacitor that ignore contact bounce and noise, then into the ESP32 (GPIO23, 13, 19, 18 and 4). |

## Other wires

| Wire | What it means |
|---|---|
| `LED_A` | ESP32 GPIO22 to the status LED's resistor. |
| `LED_M` | The link between the LED's resistor and the LED itself. |
| `SPARE_IO21`, `SPARE_IO32`, `SPARE_IO14` | Three free ESP32 pins brought out to the SPARE header for later. IO14 also goes to the microSD slot and may toggle at boot. |

## Parts, in one line each

| Ref | What it is |
|---|---|
| J1, J2 | The two sockets the ESP32 board plugs into |
| J3, J4 | Encoder 1 and 2 connectors (power, ground, A, B) |
| J5, J6 | Motor 1 and 2 control connectors (PWM, DIR, ground) |
| J7 to J10 | Limit switches 1 to 4 |
| J11 | Emergency-stop sense input |
| J12 | Spare header (ground, 3.3 V, three GPIOs) |
| J13 | Optional 5 V tap for a driver's logic supply. Leave it unwired unless the driver's 5 V pin is confirmed to be an input |
| JP1 | Encoder voltage jumper |
| D1 | Green status LED |
| TP1 to TP3 | Test points for 3.3 V, 5 V and ground, for a multimeter |

## Status

This guide was written from `board.py` and describes the design as it is defined there. It has
not been compared against the physical boards. Pin positions on the ESP32 sockets were read from
a product photo and need measuring before ordering (see `docs/pcb.md`).
