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
    return b


def sockpin(gpio):
    if gpio in L:
        return ("J1", L[gpio])
    return ("J2", Rt[gpio])
