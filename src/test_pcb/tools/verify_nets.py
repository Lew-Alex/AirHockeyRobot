#!/usr/bin/env python3
"""Check that the generated KiCad files wire every net that board.py defines.

Prometheus can report a board as clean even when a net lost pins (Board.net()
replaces a net's pins when called again with the same name). This script
compares the pins of every net in board.py with the pads of the generated
.kicad_pcb files and, when kicad-cli is available, with the netlist KiCad
exports from the generated schematic.

Run from anywhere:

    python3 src/test_pcb/tools/verify_nets.py [--out DIR]

Exit status is 0 when everything matches, 1 otherwise.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path

PCB_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PCB_DIR))

KICAD_CLI_MAC = "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli"
PROJECT_DIRS = ("kicad", "kicad8")
PROJECT_NAME = "airhockey_breakout"
# Pads that are expected to carry no net: the ESP32 socket pins this design does not use.
SOCKET_REFS = ("J1", "J2")


def sexp_blocks(text: str, key: str):
    """Yield every balanced '(key ...)' block in a KiCad s-expression file."""
    index = 0
    while True:
        index = text.find(key, index)
        if index < 0:
            return
        depth, end = 0, index
        while True:
            char = text[end]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    break
            end += 1
        yield text[index : end + 1]
        index = end


def design_nets() -> dict[str, frozenset[str]]:
    """Nets as board.py defines them: net name -> {'REF.PAD', ...}."""
    import board  # imported late so --help works without Prometheus installed

    built = board.build()
    return {
        name: frozenset(f"{ref}.{pad}" for ref, pad in data["pins"])
        for name, data in built.nets.items()
    }


def pcb_nets(path: Path) -> tuple[dict[str, frozenset[str]], list[str]]:
    """Nets as wired in a .kicad_pcb, plus the pads that have no net."""
    text = path.read_text()
    nets: dict[str, list[str]] = defaultdict(list)
    unnetted: list[str] = []
    for footprint in sexp_blocks(text, "(footprint "):
        ref = re.search(r'\(property "Reference" "([^"]*)"', footprint).group(1)
        for pad in sexp_blocks(footprint, "(pad "):
            number = re.match(r'\(pad "([^"]*)"', pad).group(1)
            net = re.search(r'\(net (?:\d+ )?"([^"]*)"', pad)
            if net and net.group(1):
                nets[net.group(1)].append(f"{ref}.{number}")
            else:
                unnetted.append(f"{ref}.{number}")
    return {name: frozenset(pins) for name, pins in nets.items()}, unnetted


def schematic_nets(schematic: Path, kicad_cli: str) -> set[frozenset[str]]:
    """Pin sets of every net KiCad finds in a schematic (names are ignored)."""
    with tempfile.TemporaryDirectory() as tmp:
        xml_path = Path(tmp) / "netlist.xml"
        subprocess.run(
            [kicad_cli, "sch", "export", "netlist", "--format", "kicadxml",
             "-o", str(xml_path), str(schematic)],
            check=True, capture_output=True,
        )
        root = ET.parse(xml_path)
    found = {
        frozenset(f"{n.get('ref')}.{n.get('pin')}" for n in net.findall("node"))
        for net in root.iter("net")
    }
    return {pins for pins in found if len(pins) > 1}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=PCB_DIR / "out",
                        help="Prometheus output folder (default: src/test_pcb/out)")
    args = parser.parse_args()

    intended = design_nets()
    failures = 0
    print(f"board.py defines {len(intended)} nets")

    kicad_cli = shutil.which("kicad-cli") or (KICAD_CLI_MAC if Path(KICAD_CLI_MAC).exists() else None)

    for project in PROJECT_DIRS:
        folder = args.out / project
        pcb_path = folder / f"{PROJECT_NAME}.kicad_pcb"
        if not pcb_path.exists():
            print(f"[{project}] missing {pcb_path}")
            failures += 1
            continue

        actual, unnetted = pcb_nets(pcb_path)
        mismatched = sorted(name for name in set(intended) | set(actual)
                            if intended.get(name) != actual.get(name))
        single_pin = sorted(name for name, pins in actual.items() if len(pins) < 2)
        stray = [pad for pad in unnetted
                 if not pad.startswith(tuple(f"{ref}." for ref in SOCKET_REFS))
                 and not pad.startswith("H")]  # H*: mounting holes have no net by design
        unused_socket = sorted(pad for pad in unnetted if pad.startswith(tuple(f"{r}." for r in SOCKET_REFS)))

        print(f"[{project}] pcb: {len(actual)} nets, mismatches: {mismatched or 'none'}, "
              f"single-pin nets: {single_pin or 'none'}, pads without a net: {stray or 'none'} "
              f"(+{len(unused_socket)} unused ESP32 socket pins)")
        failures += bool(mismatched or single_pin or stray)

        schematic = folder / f"{PROJECT_NAME}.kicad_sch"
        if kicad_cli and schematic.exists():
            same = schematic_nets(schematic, kicad_cli) == set(intended.values())
            print(f"[{project}] schematic netlist matches board.py: {same}")
            failures += not same
        elif not kicad_cli:
            print(f"[{project}] schematic check skipped (kicad-cli not found)")

    print("OK" if not failures else f"FAILED ({failures} problem(s))")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
