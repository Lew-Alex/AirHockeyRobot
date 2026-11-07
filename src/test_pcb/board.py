"""Air-hockey robot: ESP32-DevKitC V4 signal breakout (signal only; 24 V stays off-board).

ASSUMED (not from a datasheet page; verify against your DevKitC V4 silkscreen before ordering):
  - DevKitC V4 38-pin header order (see L / R below) and 25.4 mm (1000 mil) row spacing.
  - Pin choices avoid strapping (0,2,5,12,15) and flash (6-11) GPIOs, and IO16/IO17
    (wired to PSRAM on WROVER-based DevKitC boards; only IO16 is broken out, on the spare header).
  - JP1 needs a 2.54 mm jumper shunt (not in the BOM): 1-2 = 3V3, 2-3 = 5V encoder supply.
  - J13 is an optional 5 V (USB) tap for a driver's logic supply; leave it unwired unless the
    driver's 5V pin is confirmed to be an input.

NOTE: Board.net() REPLACES a net's pins when called again with the same name, so nets
shared across sections (GND, V3, V5, ENCVCC) are collected with join() and created once
at the end of build(). Every other net name is used exactly once (net() below checks this).
"""
from collections import defaultdict

from pcb import Board

W, H = 86.0, 64.0
OUT = [(0, 0), (W, 0), (W, H), (0, H)]

R = "Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P2.54mm_Vertical"
C = "Capacitor_THT:C_Disc_D3.0mm_W2.0mm_P2.50mm"
SOCK = "Connector_PinSocket_2.54mm:PinSocket_1x19_P2.54mm_Vertical"
XH = "Connector_JST:JST_XH_B{n}B-XH-A_1x0{n}_P2.50mm_Vertical"
HDR = "Connector_PinHeader_2.54mm:PinHeader_1x0{n}_P2.54mm_Vertical"

# DevKitC V4, pin 1 = antenna end. name -> socket pin number.
# J1 (left): 3V3 EN IO36 IO39 IO34 IO35 IO32 IO33 IO25 IO26 IO27 IO14 IO12 GND IO13 SD2 SD3 CMD 5V
# J2 (right): GND IO23 IO22 TX RX IO21 GND IO19 IO18 IO5 IO17 IO16 IO4 IO0 IO2 IO15 SD1 SD0 CLK
L = dict(V3="1", IO36="3", IO39="4", IO34="5", IO35="6", IO32="7", IO33="8", IO25="9",
         IO26="10", IO27="11", IO14="12", GND="14", IO13="15", V5="19")
Rt = dict(GND1="1", IO23="2", IO22="3", IO21="6", GND2="7", IO19="8", IO18="9",
          IO16="12", IO4="13")

# Shared nets: created once, after every section has added its pins.
SHARED = {
    "GND": dict(amps=0.3),
    "V3": dict(amps=0.3, volts=3.3),
    "V5": dict(amps=0.3, volts=5.0),
    "ENCVCC": dict(amps=0.2, volts=5.0),   # 3V3 or 5V via JP1; 5 V is the worst case
}


def build():
    b = Board("airhockey_breakout", OUT, thickness=1.6, copper_oz=1.0, rules="jlcpcb-2")
    shared = defaultdict(list)
    used = set()

    def join(name, *pins):
        """add pins to a shared net (GND, V3, V5, ENCVCC)"""
        shared[name].extend(pins)

    def net(name, pins):
        """a single-use signal net; a repeated name would silently replace the earlier pins"""
        if name in used or name in SHARED:
            raise ValueError(f"net {name} defined twice")
        used.add(name)
        b.net(name, pins)

    # ESP32 dev board sockets, pin 1 at the top, rows 25.4 mm apart
    b.place("J1", SOCK, (30.8, 56.6), 0, "ESP32 DevKitC L")
    b.place("J2", SOCK, (56.2, 56.6), 0, "ESP32 DevKitC R")

    # --- left edge: motor drivers (PWM, DIR, GND) and encoders (VCC, GND, A, B)
    b.place("J3", XH.format(n=4), (5.0, 58.5), 270, "ENC1")
    b.place("J4", XH.format(n=4), (5.0, 44.5), 270, "ENC2")
    b.place("J5", XH.format(n=3), (5.0, 30.5), 270, "MOTOR1")
    b.place("J6", XH.format(n=3), (5.0, 19.5), 270, "MOTOR2")
    # encoder supply select: 1-2 = 3V3, 2-3 = 5V
    b.place("JP1", HDR.format(n=3), (19.0, 11.0), 90, "ENC_VCC", lcsc="C49257")

    # --- right edge: 4 limit switches + e-stop sense (NC to GND)
    for i, y in enumerate((55.0, 46.0, 37.0, 28.0, 19.0)):
        b.place(f"J{7+i}", XH.format(n=2), (81.0, y), 90, ["LIM1", "LIM2", "LIM3", "LIM4", "ESTOP"][i])
    # spare GPIO header
    b.place("J12", HDR.format(n=6), (67.0, 11.0), 90, "SPARE", lcsc="C37208")
    # optional 5 V tap for a driver's logic supply: a single recessed female socket, live only
    # when a wire is plugged in. Do NOT connect it to a driver pin that is a 5 V OUTPUT.
    b.place("J13", "Connector_PinSocket_2.54mm:PinSocket_1x01_P2.54mm_Vertical", (5.0, 8.0), 0, "DRV_5V")

    # mounting holes (M3)
    for x, y in ((13.0, 4.0), (73.0, 4.0), (73.0, H - 4), (13.0, H - 4)):
        b.hole((x, y), d=3.2)

    # --- motor outputs: GPIO -> 220R -> connector, 10k pull-down at the connector
    motors = [("1", "IO25", "IO26", "J5"), ("2", "IO27", "IO33", "J6")]
    for m, pwm, dr, con in motors:
        for sig, gpio, pin in (("PWM", pwm, "1"), ("DIR", dr, "2")):
            rs, rp = f"RS_{sig}{m}", f"RP_{sig}{m}"
            b.place(rs, R, None, 0, "220")
            b.place(rp, R, None, 0, "10k")
            net(f"{sig}{m}_MCU", [(rs, "1"), sockpin(gpio)])
            net(f"{sig}{m}", [(rs, "2"), (rp, "1"), (con, pin)])
            join("GND", (rp, "2"))
        join("GND", (con, "3"))

    # --- encoders: connector -> 4.7k pull-up (3V3) at connector, 1k + 330pF filter to GPIO
    encs = [("1", "IO34", "IO35", "J3"), ("2", "IO36", "IO39", "J4")]
    for e, a, bb, con in encs:
        join("ENCVCC", (con, "1"))
        join("GND", (con, "2"))
        b.place(f"CE{e}", C, None, 0, "100nF")
        join("ENCVCC", (f"CE{e}", "1"))
        join("GND", (f"CE{e}", "2"))
        for ch, gpio, pin in (("A", a, "3"), ("B", bb, "4")):
            pu, rf, cf = f"RU_E{e}{ch}", f"RF_E{e}{ch}", f"CF_E{e}{ch}"
            b.place(pu, R, None, 0, "4.7k")
            b.place(rf, R, None, 0, "1k")
            b.place(cf, C, None, 0, "330pF")
            net(f"E{e}{ch}_RAW", [(con, pin), (pu, "1"), (rf, "1")])
            net(f"E{e}{ch}", [(rf, "2"), (cf, "1"), sockpin(gpio)])
            join("V3", (pu, "2"))
            join("GND", (cf, "2"))
    join("V3", ("JP1", "1"))
    join("ENCVCC", ("JP1", "2"))
    join("V5", ("JP1", "3"))
    join("V5", ("J13", "1"))

    # --- NC switches to GND: 10k pull-up to 3V3 at the connector, 1k series, 100nF to GND at the GPIO
    sw = [("LIM1", "J7", "IO23"), ("LIM2", "J8", "IO13"), ("LIM3", "J9", "IO19"),
          ("LIM4", "J10", "IO18"), ("ESTOP", "J11", "IO4")]
    for n, con, gpio in sw:
        pu, rs, cd = f"RU_{n}", f"RS_{n}", f"CD_{n}"
        b.place(pu, R, None, 0, "10k")
        b.place(rs, R, None, 0, "1k")
        b.place(cd, C, None, 0, "100nF")
        net(f"{n}_RAW", [(con, "1"), (pu, "1"), (rs, "1")])
        net(n, [(rs, "2"), (cd, "1"), sockpin(gpio)])
        join("V3", (pu, "2"))
        join("GND", (con, "2"), (cd, "2"))

    # --- status LED: GPIO22 -> 1k -> LED anode (pad 2); cathode (pad 1) -> GND
    b.place("D1", "LED_THT:LED_D3.0mm", None, 0, "GREEN")
    b.place("RL1", R, None, 0, "1k")
    net("LED_A", [sockpin("IO22"), ("RL1", "1")])
    net("LED_M", [("RL1", "2"), ("D1", "2")])
    join("GND", ("D1", "1"))

    # --- spare header: GND 3V3 IO21 IO32 IO14 IO16 (IO16: WROOM only; IO14 toggles at boot)
    join("GND", ("J12", "1"))
    join("V3", ("J12", "2"))
    for pin, gpio in (("3", "IO21"), ("4", "IO32"), ("5", "IO14"), ("6", "IO16")):
        net(f"SPARE_{gpio}", [("J12", pin), sockpin(gpio)])

    # --- sockets: power and ground
    join("V3", ("J1", L["V3"]))
    join("V5", ("J1", L["V5"]))
    join("GND", ("J1", L["GND"]), ("J2", Rt["GND1"]), ("J2", Rt["GND2"]))

    # --- test points
    for ref, name in (("TP1", "V3"), ("TP2", "V5"), ("TP3", "GND")):
        b.place(ref, "TestPoint:TestPoint_THTPad_D2.0mm_Drill1.0mm", None, 0, name)
        join(name, (ref, "1"))

    # --- shared nets, each created once with all of its pins
    for name, opts in SHARED.items():
        pins = list(dict.fromkeys(shared[name]))
        if len(pins) < 2:
            raise ValueError(f"shared net {name} has fewer than 2 pins: {pins}")
        b.net(name, pins, **opts)

    b.pour("GND", "B", OUT)
    b.pour("GND", "F", OUT)
    return b


def sockpin(gpio):
    if gpio in L:
        return ("J1", L[gpio])
    return ("J2", Rt[gpio])
