"""Air-hockey robot: ESP32-DevKitC V4 signal breakout (signal only; 24 V stays off-board).

ASSUMED (not from a datasheet page; verify against your DevKitC V4 silkscreen before ordering):
  - DevKitC V4 38-pin header order (see L / R below) and 25.4 mm (1000 mil) row spacing.
  - Pin choices avoid strapping (0,2,5,12,15) and flash (6-11) GPIOs.
"""
from pcb import Board

W, H = 86.0, 64.0
OUT = [(0, 0), (W, 0), (W, H), (0, H)]

R = "Resistor_SMD:R_0603_1608Metric"
C = "Capacitor_SMD:C_0603_1608Metric"
SOCK = "Connector_PinSocket_2.54mm:PinSocket_1x19_P2.54mm_Vertical"
XH = "Connector_JST:JST_XH_B{n}B-XH-A_1x0{n}_P2.50mm_Vertical"
HDR = "Connector_PinHeader_2.54mm:PinHeader_1x0{n}_P2.54mm_Vertical"

# DevKitC V4, pin 1 = antenna end. name -> socket pin number.
# J1 (left): 3V3 EN IO36 IO39 IO34 IO35 IO32 IO33 IO25 IO26 IO27 IO14 IO12 GND IO13 SD2 SD3 CMD 5V
# J2 (right): GND IO23 IO22 TX RX IO21 GND IO19 IO18 IO5 IO17 IO16 IO4 IO0 IO2 IO15 SD1 SD0 CLK
L = dict(V3="1", IO36="3", IO39="4", IO34="5", IO35="6", IO32="7", IO33="8", IO25="9",
         IO26="10", IO27="11", GND="14", IO13="15", V5="19")
Rt = dict(GND1="1", IO23="2", IO22="3", IO21="6", GND2="7", IO19="8", IO18="9", IO17="11",
          IO16="12", IO4="13")


def build():
    b = Board("airhockey_breakout", OUT, thickness=1.6, copper_oz=1.0, rules="jlcpcb-2")

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
    # spare GPIO / UART header
    b.place("J12", HDR.format(n=6), (67.0, 11.0), 90, "SPARE", lcsc="C37208")

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
            b.net(f"{sig}{m}_MCU", [(rs, "1"), sockpin(gpio)])
            b.net(f"{sig}{m}", [(rs, "2"), (rp, "1"), (con, pin)])
            b.net("GND", [(rp, "2")])
        b.net("GND", [(con, "3")])

    # --- encoders: connector -> 4.7k pull-up (3V3) at connector, 1k + 330pF filter to GPIO
    encs = [("1", "IO34", "IO35", "J3"), ("2", "IO36", "IO39", "J4")]
    for e, a, bb, con in encs:
        b.net(f"ENCVCC", [(con, "1")])
        b.net("GND", [(con, "2")])
        b.place(f"CE{e}", C, None, 0, "100nF")
        b.net("ENCVCC", [(f"CE{e}", "1")])
        b.net("GND", [(f"CE{e}", "2")])
        for ch, gpio, pin in (("A", a, "3"), ("B", bb, "4")):
            pu, rf, cf = f"RU_E{e}{ch}", f"RF_E{e}{ch}", f"CF_E{e}{ch}"
            b.place(pu, R, None, 0, "4.7k")
            b.place(rf, R, None, 0, "1k")
            b.place(cf, C, None, 0, "330pF")
            b.net(f"E{e}{ch}_RAW", [(con, pin), (pu, "1"), (rf, "1")])
            b.net(f"E{e}{ch}", [(rf, "2"), (cf, "1"), sockpin(gpio)])
            b.net("V3", [(pu, "2")], amps=0.3)
            b.net("GND", [(cf, "2")])
    b.net("ENCVCC", [("JP1", "2")], amps=0.2)
    b.net("V3", [("JP1", "1")], amps=0.3)
    b.net("V5", [("JP1", "3")], amps=0.3)

    # --- NC switches to GND: 10k pull-up to 3V3 at the connector, 1k series, 100nF to GND at the GPIO
    sw = [("LIM1", "J7", "IO16"), ("LIM2", "J8", "IO17"), ("LIM3", "J9", "IO19"),
          ("LIM4", "J10", "IO18"), ("ESTOP", "J11", "IO4")]
    for n, con, gpio in sw:
        pu, rs, cd = f"RU_{n}", f"RS_{n}", f"CD_{n}"
        b.place(pu, R, None, 0, "10k")
        b.place(rs, R, None, 0, "1k")
        b.place(cd, C, None, 0, "100nF")
        b.net(f"{n}_RAW", [(con, "1"), (pu, "1"), (rs, "1")])
        b.net(n, [(rs, "2"), (cd, "1"), sockpin(gpio)])
        b.net("V3", [(pu, "2")], amps=0.3)
        b.net("GND", [(con, "2"), (cd, "2")])

    # --- status LED: GPIO22 -> 1k -> LED -> GND
    b.place("D1", "LED_SMD:LED_0603_1608Metric", None, 0, "GREEN")
    b.place("RL1", R, None, 0, "1k")
    b.net("LED_A", [sockpin("IO22"), ("RL1", "1")])
    b.net("LED_M", [("RL1", "2"), ("D1", "2")])
    b.net("GND", [("D1", "1")])

    # --- spare header: GND 3V3 IO21 IO23 IO32 IO13
    b.net("GND", [("J12", "1")])
    b.net("V3", [("J12", "2")], amps=0.3)
    for pin, gpio in (("3", "IO21"), ("4", "IO23"), ("5", "IO32"), ("6", "IO13")):
        b.net(f"SPARE_{gpio}", [("J12", pin), sockpin(gpio)])

    return b


def sockpin(gpio):
    if gpio in L:
        return ("J1", L[gpio])
    return ("J2", Rt[gpio])
