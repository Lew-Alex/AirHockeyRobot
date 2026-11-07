---
name: pcb-build
description: Rebuild, verify and export the air-hockey breakout PCB in src/test_pcb with Prometheus. Use whenever board.py, req.json or the PCB outputs change, or the user asks to rebuild, check or prepare the board for ordering.
---

# Building the breakout PCB

The board lives in `src/test_pcb`. `board.py` defines it, `req.json` holds the
requirements, and `out/` holds the generated KiCad projects, Gerbers, BOM and
reports.

## Rebuild

1. FreeRouting 2.0.1 needs Java 21, but this machine's default is Java 17. A
   Java 21 runtime is cached in `~/.cache/prometheus/java21/`. If the path
   below does not exist, tell the user instead of installing system software.

   ```bash
   export PROMETHEUS_JAVA=~/.cache/prometheus/java21/jdk-21.0.13+9-jre/Contents/Home/bin/java
   cd src/test_pcb
   prometheus board.py out/ --spec req.json --json
   ```

2. Read `clean`, `findings`, `critic`, `router` and `kicad_drc.run` in the JSON.
   Say which router ran and whether KiCad DRC ran.
3. **Always run the net check. A clean Prometheus result is not enough.**

   ```bash
   python3 tools/verify_nets.py
   ```

   It compares every net in `board.py` with the pads in both generated KiCad
   projects and with KiCad's own netlist export of the schematic. It must print
   `OK`.

## board.py rules

- `Board.net(name, pins)` **replaces** the net's pins when the same name is used
  again. Shared nets (GND, V3, V5, ENCVCC) are therefore collected with `join()`
  and created once at the end of `build()`. Single-use signal nets go through the
  local `net()` helper, which raises on a repeated name. Never call `b.net()`
  directly for a name that appears more than once.
- Do not loosen rules to clear a finding. Change the design (positions, widths,
  outline) and rebuild.
- Mark each assumed pin or chosen value in the file's header comment. The
  DevKitC V4 header order and 25.4 mm row spacing are still assumptions.

## Before telling the user the board is ready

- `clean` is true, `verify_nets.py` prints `OK`, and DRC reports 0 unconnected items.
- State what is still open: the board is **not ordered, assembled or tested**.
  Open items are the DevKitC pinout check, the encoder supply voltage for JP1
  (needs a jumper shunt, which is not in the BOM) and the choice of motor driver.
- Gerbers for ordering are `src/test_pcb/out/gerbers.zip` (upload the zip, do not
  unzip it). The BOM and CPL files are only for JLCPCB assembly, which this
  through-hole board does not use.
- Regenerating `out/` produces very large diffs. Commit them separately from
  `board.py` changes when practical.
