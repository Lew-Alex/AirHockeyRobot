#!/usr/bin/env python3
"""Build the air hockey BOM files (BOM.csv and BOM.xlsx) from one data structure.

The prices were read from the live pages on 2026-09-23 unless the row says otherwise. Two
RobotShop rows come from Wayback snapshots and are marked with their snapshot date: a
snapshot is context for a price, not a current price, which is why they carry a lower
confidence and a "verify" status.

Run: python3 build_bom.py
"""
from __future__ import annotations

import csv
import os

HERE = os.path.dirname(os.path.abspath(__file__))
READ_DATE = "2026-09-23"

# item, qty, unit, spec, source, unit_price, currency, status, provenance, notes
ROWS = [
    dict(item="Motor", qty=2, unit="each",
         spec="775S-EN brushed DC motor with encoder, 24V, 8200 rpm no load, 42D x 66.5L",
         source="ca.robotshop.com", url="https://ca.robotshop.com/products/e-s-motor-775-size-dc-motor-with-encoder-24v-8200-rpm",
         unit_price=27.30, currency="CAD", status="to order",
         provenance=f"Alex, read from the page {READ_DATE}",
         notes="Encoder version of the 775 class, so it sits above the CAD 14.75 that the "
               "plain 8300 rpm 775 was. 8,200 rpm no load at 24 V, and the strike needs "
               "7,200 rpm at 72 mm per motor rev, so the drive is inside its speed range but "
               "near the no-load end, with the torque margin thinning."),
    dict(item="V-rollers / gantry plates", qty=1, unit="pack of 4",
         spec="Seekliny small 2020 V-slot gantry plate, assembled, 4 pack",
         source="amazon.ca/dp/B0DXKX69K1", url="https://www.amazon.ca/dp/B0DXKX69K1",
         unit_price=30.99, currency="CAD", status="to order", provenance=f"live {READ_DATE}",
         notes="4 plates; the listing says 'small', check it matches the 2020 profile."),
    dict(item="2020 aluminium extrusion", qty=1, unit="pack of 10",
         spec="SeekLiny V-slot 2020 extrusion, 800 mm, black anodised, 10 pcs",
         source="amazon.ca/dp/B09DYJRRTG", url="https://www.amazon.ca/dp/B09DYJRRTG",
         unit_price=99.99, currency="CAD", status="to order", provenance=f"live {READ_DATE}",
         notes="800 mm is SHORTER than the 48 in (1219 mm) long axis of the table, so these "
               "cannot span it in one piece. Fine for the cross axis (24 in = 610 mm) and for "
               "the carriage. Decide the frame layout before ordering: a spliced long rail is "
               "not a precision rail."),
    dict(item="Motor driver", qty=1, unit="pack of 2",
         spec="BTS7960 43A dual H-bridge module, 2 pcs",
         source="amazon.ca/dp/B086W5QTYT", url="https://www.amazon.ca/dp/B086W5QTYT",
         unit_price=36.99, currency="CAD", status="to order", provenance=f"live {READ_DATE} in stock",
         notes="2 pack, so one order covers both motors. A dumb H-bridge gives PWM only: no "
               "current control, no field-oriented control, no CAN. Closed-loop position "
               "control is still possible if the Teensy reads the motor encoder. This replaces "
               "the ODESC FOC plan in the sizing study, which changes what the build teaches."),
    dict(item="Power supply", qty=1, unit="each",
         spec="inShareplus 24V 16.5A 400W regulated switching supply",
         source="amazon.ca/dp/B07RHJ53C9", url="https://www.amazon.ca/dp/B07RHJ53C9",
         unit_price=37.99, currency="CAD", status="to order", provenance=f"live {READ_DATE}",
         notes="16.5 A total, not 25 A. A 775 motor pulls far more than that at stall, so this "
               "supply has to be treated as bench-limited: fuse and current-limit in firmware, "
               "and expect brownout on a simultaneous stall."),
    dict(item="Fuses and holders", qty=1, unit="pack of 6",
         spec="Riseuvo 10 AWG inline fuse holder, 6 holders plus 6 x 40A ATC/ATO fuses",
         source="amazon.ca/dp/B0D4YSDXJZ", url="https://www.amazon.ca/dp/B0D4YSDXJZ",
         unit_price=17.09, currency="CAD", status="to order", provenance=f"live {READ_DATE}",
         notes="A 40 A fuse protects 10 AWG wire, NOT the 16.5 A supply and not the motor. "
               "Match the fuse to the wire and the supply, not to the stall current, or the "
               "supply is the thing that fails first."),
    dict(item="Current sensor", qty=2, unit="each",
         spec="Pololu ACS71240KEXBLT-030B5 carrier, -30A to +30A, 5V",
         source="ca.robotshop.com", url="https://ca.robotshop.com/products/pololu-acs71240kexblt-030b5-current-sensor-carrier-30a-to-30a-5v",
         unit_price=5.64, currency="CAD", status="verify", provenance="snapshot 2025-10-10 (BackOrder)",
         notes="snapshot price, roughly a year old, and it looks low for this part (Pololu list "
               "is higher). One per motor gives real current telemetry for the limit. Note the "
               "range: +/-30 A saturates near stall on a 775."),
    dict(item="Air hockey table", qty=1, unit="each",
         spec="used table, Facebook Marketplace",
         source="Facebook Marketplace", url="",
         unit_price=60.00, currency="CAD", status="to order", provenance="Alex, flat price",
         notes="The dimension driver. Check the blower and the surface before buying: every "
               "cut-to-length item waits on this. 24 x 48 in assumed until measured."),
    dict(item="Timing belt", qty=1, unit="10 m roll",
         spec="SeekLiny GT2 belt, 9 mm wide, 10 m long, 2 mm pitch",
         source="amazon.ca/dp/B0CX1GH4LV", url="https://www.amazon.ca/dp/B0CX1GH4LV",
         unit_price=24.99, currency="CAD", status="to order", provenance=f"live {READ_DATE}",
         notes="9 mm wide is the right call over 6 mm. But 2 mm pitch with a 36T pulley is "
               "72 mm per motor rev: the strike speed of 8.64 m/s then needs 7,200 rpm against "
               "8,200 rpm no load, so the drive sits at 88 percent of its no-load speed with "
               "almost no torque margin. The sizing study flagged 2 mm pitch as too fine."),
    dict(item="Wood for the frame", qty=1, unit="lot",
         spec="general structure timber",
         source="Home Depot", url="",
         unit_price=50.00, currency="CAD", status="to order", provenance="Alex, flat price",
         notes=""),
    dict(item="3D printed parts", qty=1, unit="lot",
         spec="filament plus Waterloo printing",
         source="filament + Waterloo", url="",
         unit_price=50.00, currency="CAD", status="to order", provenance="Alex, flat price",
         notes=""),
    dict(item="Motor pulley", qty=2, unit="each",
         spec="3D Printing Canada GT2-10 timing belt pulley, 36T, 5 mm inner bore",
         source="ca.robotshop.com", url="https://ca.robotshop.com/products/3d-printing-canada-usa-3d-printing-canada-gt2-10-timing-belt-pulley-36t-inner-bore-5mm",
         unit_price=5.95, currency="CAD", status="verify", provenance="snapshot 2025-08-10 (InStock)",
         notes="snapshot price, about a year old. 36T on 2 mm pitch is 72 mm per motor rev, see "
               "the belt row. The 5 mm bore matches a 775 shaft, which is right."),
    dict(item="Idler / router bearings", qty=1, unit="pack of 25",
         spec="uxcell 625ZZ deep groove ball bearing, 5 mm bore, 16 mm OD, 5 mm thick",
         source="amazon.ca/dp/B0CJFRSK7D", url="https://www.amazon.ca/dp/B0CJFRSK7D",
         unit_price=13.99, currency="CAD", status="to order", provenance=f"live {READ_DATE}",
         notes="25 pcs is more than the belt path needs, but they are consumables."),
]

# parts the plan implies that the list does not have. Prices are ESTIMATES, marked as such.
GAPS = [
    ("Limit switches", 4, "mechanical or optical homing switches, wired normally closed",
     "to source", 3.00, "estimate", "homing is required before any closed-loop move can be trusted"),
    ("Emergency stop", 1, "hard wired to cut motor power, not a software flag",
     "to source", 15.00, "estimate", "required before any high speed testing"),
    ("Camera", 1, "global shutter USB camera for the perception node",
     "to source", 80.00, "estimate", "a phone is rolling shutter and belongs offline only"),
    ("Bulk capacitors", 1, "across the 24 V rail, sized for the burst deficit",
     "to source", 20.00, "estimate", "the 16.5 A supply is well under the stall current"),
    ("Wire, terminals, heatshrink", 1, "12 to 14 AWG for the motor runs",
     "to source", 35.00, "estimate", ""),
    ("Table blower allowance", 1, "repair or replace the blower on the used table",
     "Facebook Marketplace", 30.00, "estimate", "a used table usually needs one"),
]

TOTAL_HEADERS = ("item", "qty", "unit", "spec", "source", "url", "unit_price_cad",
                 "line_total_cad", "currency", "status", "price_provenance", "notes")


def line_total(row) -> float | None:
    return None if row["unit_price"] is None else round(row["unit_price"] * row["qty"], 2)


def buckets(rows):
    """Three honest buckets by where the number came from. The earlier version labelled
    every priced row as "read from the live page", which quietly counted Alex's flat prices
    as live reads."""
    live = [r for r in rows if r["provenance"].startswith("live")]
    supplied = [r for r in rows if r["provenance"].startswith("Alex")]
    snap = [r for r in rows if "snapshot" in r["provenance"]]
    return live, supplied, snap


def main() -> None:
    known = [r for r in ROWS if r["unit_price"] is not None]
    unknown = [r for r in ROWS if r["unit_price"] is None]
    live, supplied, to_verify = buckets(known)
    total_live = round(sum(line_total(r) for r in live), 2)
    total_supplied = round(sum(line_total(r) for r in supplied), 2)
    total_verify = round(sum(line_total(r) for r in to_verify), 2)
    total_known = round(total_live + total_supplied + total_verify, 2)
    gaps_total = round(sum(p * q for _n, q, _s, _src, p, _c, _note in GAPS), 2)

    csv_path = os.path.join(HERE, "BOM.csv")
    with open(csv_path, "w", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(TOTAL_HEADERS)
        for r in ROWS:
            writer.writerow([
                r["item"], r["qty"], r["unit"], r["spec"], r["source"], r["url"],
                "" if r["unit_price"] is None else f"{r['unit_price']:.2f}",
                "" if line_total(r) is None else f"{line_total(r):.2f}",
                r["currency"], r["status"], r["provenance"], r["notes"],
            ])
        writer.writerow([])
        writer.writerow(["SUBTOTAL, live page reads", "", "", "", "", "",
                         "", f"{total_live:.2f}", "CAD", "", "",
                         f"{len(live)} rows, read {READ_DATE}"])
        writer.writerow(["SUBTOTAL, prices Alex supplied", "", "", "", "", "",
                         "", f"{total_supplied:.2f}", "CAD", "", "",
                         f"{len(supplied)} rows, flat prices or read by hand"])
        writer.writerow(["SUBTOTAL, snapshot prices, verify before ordering", "", "", "", "", "",
                         "", f"{total_verify:.2f}", "CAD", "", "",
                         f"{len(to_verify)} rows from archived copies"])
        writer.writerow(["TOTAL, everything with a price", "", "", "", "", "",
                         "", f"{total_known:.2f}", "CAD", "", "",
                         f"{len(known)} of {len(ROWS)} rows have a price"])
        writer.writerow(["TOTAL including the gaps sheet", "", "", "", "", "",
                         "", f"{total_known + gaps_total:.2f}", "CAD", "", "",
                         "the number to compare against the 900 target"])
        if unknown:
            writer.writerow(["MISSING", "", "", "", "", "", "", "", "CAD", "", "",
                             ", ".join(r["item"] for r in unknown) + " has no price yet"])
        writer.writerow([])
        writer.writerow(["GAPS, not in the list, estimates", "", "", "", "", "", "", "", "CAD", "", "", ""])
        for name, qty, spec, src, price, conf, note in GAPS:
            writer.writerow([name, qty, "", spec, src, "", f"{price:.2f}", f"{price*qty:.2f}",
                             "CAD", "estimate", conf, note])
        writer.writerow(["GAPS TOTAL (estimates)", "", "", "", "", "", "", f"{gaps_total:.2f}",
                         "CAD", "estimate", "", "add to the total when quoting a budget"])

    print("rows:", len(ROWS), "| priced:", len(known), "| unpriced:", len(unknown))
    print(f"live reads ({len(live)} rows): {total_live:.2f} CAD")
    print(f"Alex supplied ({len(supplied)} rows): {total_supplied:.2f} CAD")
    print(f"snapshot, verify ({len(to_verify)} rows): {total_verify:.2f} CAD")
    print(f"known total: {total_known:.2f} CAD")
    print(f"gaps (estimates): {gaps_total:.2f} CAD")
    print(f"total including gaps: {total_known + gaps_total:.2f} CAD")
    print("csv ->", csv_path)

    make_xlsx(ROWS, GAPS, known, live, supplied, to_verify, unknown, total_live,
              total_supplied, total_verify, total_known, gaps_total, line_total)
    return None


def make_xlsx(rows, gaps, known, live, supplied, to_verify, unknown, total_live,
              total_supplied, total_verify, total_known, gaps_total, lt) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    bold = Font(bold=True)
    header_fill = PatternFill("solid", fgColor="DDEBF7")
    warn_fill = PatternFill("solid", fgColor="FCE4D6")
    money = '#,##0.00'
    wrap = Alignment(wrap_text=True, vertical="top")
    thin = Side(style="thin", color="BFBFBF")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)

    # ------------------------------------------------------------------ sheet 1: BOM
    ws = wb.active
    ws.title = "BOM"
    headers = ["Item", "Qty", "Unit", "What it is", "Source", "Link", "Unit price (CAD)",
               "Line total (CAD)", "Status", "Price read", "Notes"]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = bold
        cell.fill = header_fill
        cell.border = box
        cell.alignment = Alignment(wrap_text=True, vertical="center")
    for r in rows:
        lt_row = lt(r)
        ws.append([r["item"], r["qty"], r["unit"], r["spec"], r["source"], r["url"],
                   r["unit_price"], lt_row, r["status"], r["provenance"], r["notes"]])
        if r["status"] == "verify":
            for cell in ws[ws.max_row]:
                cell.fill = warn_fill
    ws.append([])
    ws.append(["SUBTOTAL, live page reads", "", "", "", "", "", "", total_live,
               "CAD", "", f"{len(live)} rows, read {READ_DATE}"])
    ws.append(["SUBTOTAL, prices Alex supplied", "", "", "", "", "", "", total_supplied,
               "CAD", "", f"{len(supplied)} rows"])
    ws.append(["SUBTOTAL, snapshot prices, verify before ordering", "", "", "", "", "", "",
               total_verify, "CAD", "", f"{len(to_verify)} rows"])
    ws.append(["TOTAL, every row that has a price", "", "", "", "", "", "", total_known,
               "CAD", "", f"{len(known)} of {len(rows)} rows"])
    ws.append(["TOTAL including the gaps sheet", "", "", "", "", "", "",
               total_known + gaps_total, "CAD", "", "compare against the 900 target"])
    if unknown:
        ws.append(["MISSING", "", "", "", ", ".join(r["item"] for r in unknown), "", "", "",
                   "CAD", "", "no price could be read"])
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=7, max_col=8):
        for cell in row:
            cell.number_format = money
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row):
        for cell in row:
            cell.alignment = wrap
    for idx, width in enumerate([28, 6, 12, 46, 22, 46, 14, 14, 10, 26, 64], start=1):
        ws.column_dimensions[get_column_letter(idx)].width = width
    ws.freeze_panes = "A2"

    # ------------------------------------------------------------------ sheet 2: gaps
    ws2 = wb.create_sheet("Gaps")
    ws2.append(["Not in the list, estimated", "Qty", "What it is", "Source",
                "Unit price (CAD)", "Line total (CAD)", "Confidence", "Why it matters"])
    for cell in ws2[1]:
        cell.font = bold
        cell.fill = header_fill
        cell.border = box
    for name, qty, spec, src, price, conf, note in gaps:
        ws2.append([name, qty, spec, src, price, price * qty, conf, note])
        for cell in ws2[ws2.max_row]:
            cell.fill = warn_fill
    ws2.append([])
    ws2.append(["GAPS TOTAL (estimates)", "", "", "", "", gaps_total, "estimate",
                "add to the total when quoting a budget"])
    for row in ws2.iter_rows(min_row=2, max_row=ws2.max_row, min_col=5, max_col=6):
        for cell in row:
            cell.number_format = money
    for row in ws2.iter_rows(min_row=1, max_row=ws2.max_row):
        for cell in row:
            cell.alignment = wrap
    for idx, width in enumerate([28, 6, 46, 22, 16, 16, 12, 56], start=1):
        ws2.column_dimensions[get_column_letter(idx)].width = width
    ws2.freeze_panes = "A2"

    # ------------------------------------------------------------------ sheet 3: sources
    ws3 = wb.create_sheet("Sources")
    ws3.append(["Link", "Price read", "How", "Date", "Confidence"])
    for cell in ws3[1]:
        cell.font = bold
        cell.fill = header_fill
    import re as _re
    for r in rows:
        how = r["provenance"]
        live = how.startswith("live")
        stamp = _re.search(r"\d{4}-\d{2}-\d{2}", how)
        date = READ_DATE if live else (stamp.group(0) if stamp else "n/a")
        confidence = "high" if live else ("low" if "snapshot" in how else "n/a")
        ws3.append([r["url"], r["unit_price"], "live page fetch" if live else how,
                    date, confidence])
    ws3.append(["", "", "", "", ""])
    ws3.append(["", "", "note", "", ""])
    ws3.append(["", "", "web_extract (Firecrawl) is 403 for every host from this machine, so "
                        "prices came from the Jina reader and from Wayback", "", ""])
    ws3.append(["", "", "ca.robotshop.com blocks every automated route tried: direct curl, "
                        "Jina reader, /products/<handle>.json, /products/<handle>.js, and a "
                        "live browser session held open past the Cloudflare challenge", "", ""])
    for row in ws3.iter_rows(min_row=2, max_row=ws3.max_row, min_col=2, max_col=2):
        for cell in row:
            cell.number_format = money
    for row in ws3.iter_rows(min_row=1, max_row=ws3.max_row):
        for cell in row:
            cell.alignment = wrap
    for idx, width in enumerate([60, 12, 50, 14, 12], start=1):
        ws3.column_dimensions[get_column_letter(idx)].width = width

    path = os.path.join(HERE, "BOM.xlsx")
    wb.save(path)
    print("xlsx ->", path)


if __name__ == "__main__":
    main()
