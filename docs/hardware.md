# Hardware

Nothing in the candidate sections is a decision. Prices were read from product
pages on 2026-11-06 or 2026-11-07, in the currency shown, and exclude shipping
and duties unless stated.

## In hand or assumed

- ESP32 as the controller. The PCB takes an ESP32-DevKitC V4 on two 1x19 sockets.
  The earlier plan used a Teensy 4.1.
- Two Hall encoders on the 775 motors. Output type, supply voltage and pulses per
  revolution are **not confirmed**. Check them before setting JP1.
- Four SPDT micro limit switches (COM / NO / NC, the DAOKI JL012-13.5-2 type).
  Wire COM and NC. Leave NO unconnected.
- Motors: 24 V brushed 775 with Hall encoders. The Chihai CHR-775S-ABHL was the
  leading candidate. Confirm encoder type, PPR, pinout, shaft length, rated torque
  and **stall current**.

## Motor driver candidates

The PCB provides PWM + DIR + GND per motor on J5 and J6, and 3.3 V logic from the
ESP32. The driver must accept that.

| Candidate | Price | 3.3 V logic | Protection (as documented) | Notes |
|---|---|---|---|---|
| Cytron SHIELD-MDD10 (RobotShop RB-Cyt-273) | C$38.63 | Yes: low 0 to 0.8 V, high 1.5 to 5.5 V | Overcurrent limiting, current limit falling with board temperature, undervoltage shutdown. **No reverse-polarity protection.** | Dual, 7 to 30 V, 10 A per channel. An Arduino shield: PWM and DIR go to jumper-selected Arduino header pins. Its 5 V pin is an output (do not connect it to the ESP32). Datasheet Rev 1.0, May 2019. |
| Cytron MDD10A (RobotShop RB-Cyt-153) | C$30.99 | Yes: logic high is 3.0 V minimum | None documented. Reverse polarity is stated as unprotected. | Dual, 5 to 30 V, 10 A per channel. Inputs: GND, PWM2, DIR2, PWM1, DIR1 on a 5-way 2510 connector. User manual v2.0. |
| 2 x Pololu G2 24v13 | US$44.95 each | Yes: 1.8 to 5 V inputs | Reverse voltage, undervoltage, current limiting (30 A default), short circuit. **No thermal shutdown.** | Single channel each, 6.5 to 40 V, 13 A. PWM and DIR match the PCB. |
| 7Semi Vikram 3020D (Evelta) | INR 2,581.84 | Yes: 3.3 V and 5 V | Overcurrent, overvoltage, undervoltage lockout, thermal shutdown at 120 C | Dual, 7 to 32 V, 20 A per channel. Ships from India; Canada shipping not stated. Pinout is only an image on the page. |
| AliExpress IRF3205 dual H-bridge | C$21.48 | Not confirmed | None listed | Manual not read. Pins described as 5V, GND, PWM1, DIR1, PWM2, DIR2; the role of the 5V pin is unknown. Not recommended until verified. |

Observations, not conclusions: the SHIELD-MDD10 is the cheapest dual board with
documented protection and 3.3 V logic. The Pololu pair is the best documented but
costs more. Every option still needs a fuse and an e-stop.

## Power supply candidate

- inShareplus 24 V 16.5 A 400 W (Amazon.ca B07RHJ53C9, C$37.99). 100 to 240 V AC
  with a 110/220 V switch (use 110 V in Canada), screw terminals, fan.
  Protections are claimed in the listing. **No CSA or UL listing is shown**, and
  regulation and a trim adjustment are not stated.
- A certified Mean Well unit (for example the LRS-350-24) is the safer alternative.
  Its price was not checked.
- Keep the load under about 80% of the rating.

Before connecting a driver to any supply: measure the unloaded output (it must be
about 24 V, well under the drivers' 30 V maximum), wire the mains side with a
proper cord, earth connection and enclosure, and add a fuse.

## System-level protection (needed whichever driver is chosen)

- Fuse on the 24 V feed to the drivers, sized above running current and below the
  driver's peak rating.
- Hardware e-stop that cuts the 24 V.
- Regeneration: switching supplies can shut down when motors push current back.
  Cytron's manual recommends a battery in parallel. A large capacitor bank and
  gentler braking in firmware also help. A TVS diode alone does not solve it.
- Keyed power connectors where reverse polarity is unprotected.

## Parts for the breakout PCB (through-hole)

| Qty | Part |
|---|---|
| 1 | The PCB (upload `src/test_pcb/out/gerbers.zip`, do not unzip) |
| 1 | ESP32-DevKitC V4 (38-pin) |
| 2 | 1x19 female pin socket, 2.54 mm |
| 1 | 1x6 male pin header, 2.54 mm (J12) |
| 1 | 1x3 male pin header, 2.54 mm (JP1) and 1 jumper shunt |
| 1 | 1x1 female pin socket (J13, optional 5 V tap) |
| 5 | JST XH 2-pin vertical header, B2B-XH-A |
| 2 | JST XH 3-pin vertical header, B3B-XH-A |
| 2 | JST XH 4-pin vertical header, B4B-XH-A |
| 10 | 1 kOhm resistor |
| 9 | 10 kOhm resistor |
| 4 | 4.7 kOhm resistor |
| 4 | 220 Ohm resistor |
| 7 | 100 nF ceramic capacitor |
| 4 | 330 pF ceramic capacitor |
| 1 | 3 mm LED |
| 3 | Test point pads (optional) |

For the cable side: JST XH housings (five 2-pin, two 3-pin, two 4-pin), SXH-001T
crimp terminals (at least 24) and wire, or pre-crimped XH leads. Do not mix XH
with other JST families.
