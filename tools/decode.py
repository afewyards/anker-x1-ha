#!/usr/bin/env python3
"""Decode the undocumented high-range block (10701+) from scan_result.json."""
import json, struct

with open("/Users/kleist/Sites/anker-x1-scan/scan_result.json") as f:
    data = json.load(f)

high = {int(a): v for a, v in data["high_10701_13000"].items()}
addrs = sorted(high)
lo, hi = addrs[0], addrs[-1]
regs = {a: high.get(a, 0) for a in range(lo, hi + 1)}


def f32(hi_w, lo_w):
    return struct.unpack(">f", struct.pack(">HH", hi_w, lo_w))[0]


def ascii_swapped(a0, a1):
    """Decode registers as low-byte-first ASCII (what the X1 appears to use)."""
    out = []
    for a in range(a0, a1 + 1):
        v = regs.get(a, 0)
        out.append(v & 0xFF)
        out.append((v >> 8) & 0xFF)
    return bytes(out).split(b"\x00")[0].decode("ascii", "replace")


print("=== ASCII regions (low-byte-first) ===")
for a0, a1, guess in [(10701, 10717, "Manufacturer"), (10718, 10741, "Model/Product"),
                      (10742, 10749, "Version"), (10750, 10767, "Serial?")]:
    print(f"  {a0}-{a1:<6} {guess:14}: {ascii_swapped(a0, a1)!r}")

print("\n=== Float32 pairs from 10768 (big-endian word order) ===")
a = 10768
while a < 11000:
    hw, lw = regs.get(a, 0), regs.get(a + 1, 0)
    val = f32(hw, lw)
    if abs(val) > 1e-6 and abs(val) < 1e9:
        print(f"  {a}/{a+1}: {val:12.4f}   (raw {hw:#06x} {lw:#06x})")
    a += 2
