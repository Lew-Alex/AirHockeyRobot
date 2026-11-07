# Breakout PCB

`src/test_pcb/board.py` defines a 86 x 64 mm, 2-layer, through-hole board for
JLCPCB. It is a **signal-only** breakout: an ESP32-DevKitC V4 plugs into two
sockets, and the laptop's USB powers it. There is no 24 V on this board. The 24 V
supply goes straight to the motor drivers.

**Status:** Prometheus reports clean, KiCad DRC finds 0 unconnected items, and
`tools/verify_nets.py` confirms all 36 nets match `board.py`. The board has **not
been ordered, assembled or tested.**

## Connectors

All JST XH connectors are vertical through-hole headers (B2B, B3B, B4B-XH-A).

| Ref | Label | Type | Pins | ESP32 pins |
|---|---|---|---|---|
| J3 | ENC1 | XH 4-pin | 1 VCC, 2 GND, 3 A, 4 B | A IO34, B IO35 |
| J4 | ENC2 | XH 4-pin | 1 VCC, 2 GND, 3 A, 4 B | A IO36, B IO39 |
| J5 | MOTOR1 | XH 3-pin | 1 PWM, 2 DIR, 3 GND | PWM IO25, DIR IO26 |
| J6 | MOTOR2 | XH 3-pin | 1 PWM, 2 DIR, 3 GND | PWM IO27, DIR IO33 |
| J7 | LIM1 | XH 2-pin | 1 signal, 2 GND | IO23 |
| J8 | LIM2 | XH 2-pin | 1 signal, 2 GND | IO13 |
| J9 | LIM3 | XH 2-pin | 1 signal, 2 GND | IO19 |
| J10 | LIM4 | XH 2-pin | 1 signal, 2 GND | IO18 |
| J11 | ESTOP | XH 2-pin | 1 signal, 2 GND | IO4 |
| J12 | SPARE | 1x6 header | GND, 3V3, IO21, IO32, IO14, IO16 | as listed |
| J13 | DRV_5V | 1x1 female socket | 5 V (USB) | none |
| JP1 | ENC_VCC | 1x3 header | 1 = 3V3, 2 = encoder VCC, 3 = 5V | none |
| D1 | status LED | 3 mm LED | via 1 kOhm | IO22 |
| J1, J2 | ESP32 | 2 x 1x19 sockets | DevKitC V4 | n/a |

## Circuits

- **Motor outputs:** GPIO, then 220 Ohm in series, to the connector, with a
  10 kOhm pull-down at the connector so the driver sees a defined input while the
  ESP32 boots. The driver must accept 3.3 V logic.
- **Encoders:** each A and B line has a 4.7 kOhm pull-up to 3.3 V at the connector,
  then 1 kOhm and 330 pF to the GPIO. IO34 to IO39 are input-only pins with no
  internal pull-ups, which is why the pull-ups are external.
- **Limit switches and e-stop sense:** wired normally closed to GND. 10 kOhm
  pull-up to 3.3 V at the connector, then 1 kOhm series and 100 nF to GND at the
  GPIO. Closed reads low; an open switch or a broken wire reads high.
  The e-stop input only informs the firmware. It does not cut motor power.
- **Encoder supply:** JP1 selects 3.3 V or 5 V through a jumper shunt. **With no
  shunt the encoders are unpowered**, and the shunt is not in the BOM. The pull-ups
  go to 3.3 V in both positions, so a 5 V encoder with push-pull outputs would put
  5 V on the ESP32 inputs.
- **J13:** an optional 5 V tap for a driver's logic supply. Leave it unwired unless
  the driver's 5V pin is confirmed to be an input. Never connect it to a driver pin
  that is a 5 V output.

## Pin choices

GPIO 0, 2, 5, 12 and 15 (strapping) and 6 to 11 (flash) are unused. IO16 and IO17
are PSRAM pins on WROVER-based DevKitC boards, so only IO16 is exposed, on the
spare header, and works only on WROOM boards. IO14 toggles at boot.

## Build and order

```bash
export PROMETHEUS_JAVA=~/.cache/prometheus/java21/jdk-21.0.13+9-jre/Contents/Home/bin/java
cd src/test_pcb
prometheus board.py out/ --spec req.json --json
python3 tools/verify_nets.py
```

Upload `out/gerbers.zip` as it is (2 layers, 86 x 64 mm, 1.6 mm, 1 oz, HASL). The
BOM and CPL files are for JLCPCB assembly and are not needed for hand soldering.

## Open items before ordering

1. **DevKitC V4 pin order and the 25.4 mm row spacing are assumptions** taken from
   memory of the pinout. Check them against the actual board.
2. **Encoder supply voltage and output type** (decides JP1 and whether the inputs
   need protection).
3. **Motor driver choice** (see `hardware.md`). Check logic level, input pins and
   whether its 5V pin is an input or an output.
4. J5 and J6 each carry a GND wire, but most drivers have a single GND pin. Splice
   the two ground wires together.
5. Silkscreen labels for J5 and J9 did not fit and are left off the board.

## Lesson from this board

`Board.net()` replaces a net's pins when the same name is used again. An earlier
version of `board.py` called it many times for GND, 3V3, 5V and the encoder
supply, so each ended up with a single pin, yet the design check reported clean.
`board.py` now collects shared nets and creates each once, and
`tools/verify_nets.py` checks the generated files against it.
