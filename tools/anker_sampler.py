#!/usr/bin/env python3
"""Anker X1 sampler — HAOS edition v2. Fresh connection per poll + strict MBAP
validation + value sanity checks, so a hiccup can never desync the framing.
Appends to /share/anker_charge_log.csv."""
import socket, struct, time, sys, datetime

HOST, PORT, UNIT, TIMEOUT = "172.20.0.42", 502, 1, 3.0
INTERVAL = float(sys.argv[1]) if len(sys.argv) > 1 else 5.0
DURATION = float(sys.argv[2]) if len(sys.argv) > 2 else 86400.0
CSV = "/share/anker_charge_log.csv"
BATT = {0: "Standby", 1: "Charging", 2: "Discharging", 3: "Sleep"}


def recvn(s, n):
    b = b""
    while len(b) < n:
        c = s.recv(n - len(b))
        if not c:
            raise ConnectionError("closed")
        b += c
    return b


def read(s, tid, fc, addr, count):
    s.sendall(struct.pack(">HHHB", tid, 0, 6, UNIT) + struct.pack(">BHH", fc, addr, count))
    rtid, proto, length, unit = struct.unpack(">HHHB", recvn(s, 7))
    body = recvn(s, length - 1)
    if rtid != tid or proto != 0:
        raise ValueError("MBAP mismatch tid=%d/%d proto=%d" % (rtid, tid, proto))
    if body[0] != fc:
        raise ValueError("func mismatch %d/%d" % (body[0], fc))
    bc = body[1]
    if bc != count * 2:
        raise ValueError("bytecount %d != %d" % (bc, count * 2))
    return list(struct.unpack(">%dH" % (bc // 2), body[2:2 + bc]))


def i32(a, base, addr):
    v = a[addr - base] | (a[addr - base + 1] << 16)
    return v - 0x100000000 if v >= 0x80000000 else v
def u16(a, base, addr):
    return a[addr - base]


def sane(soc, ac, bat, bk, pv):
    return 0 <= soc <= 100 and abs(ac) < 30000 and abs(bat) < 30000 and abs(bk) < 30000 and -100 <= pv < 30000


cols = ["ts", "soc", "status", "pv", "ac_active", "battery", "charge",
        "discharge", "backup", "grid", "load", "ac_minus_batt", "pv_plus_batt_minus_ac",
        "soh", "pack_voltage"]
import os
if not os.path.exists(CSV) or os.path.getsize(CSV) == 0:
    with open(CSV, "w") as f:
        f.write(",".join(cols) + "\n")

start = time.time()
tid = 0
last_status = None
print(f"sampler v2 start interval={INTERVAL}s duration={DURATION}s -> {CSV}", flush=True)
while time.time() - start < DURATION:
    s = None
    try:
        s = socket.create_connection((HOST, PORT), timeout=TIMEOUT)
        s.settimeout(TIMEOUT)
        tid = (tid + 1) & 0xFFFF
        a = read(s, tid, 0x04, 10000, 40)
        tid = (tid + 1) & 0xFFFF
        g = read(s, tid, 0x04, 10224, 30)
        s.close(); s = None

        soc = u16(a, 10000, 10014); status = u16(a, 10000, 10001)
        pv = i32(a, 10000, 10002); ac = i32(a, 10000, 10006); bat = i32(a, 10000, 10008)
        grid = i32(a, 10000, 10012); load = i32(a, 10000, 10010); backup = i32(g, 10224, 10233)
        soh = u16(a, 10000, 10015); pack_v = u16(g, 10224, 10253) / 10.0
        if not sane(soc, ac, bat, backup, pv):
            raise ValueError("insane values soc=%s ac=%s bat=%s bk=%s pv=%s" % (soc, ac, bat, backup, pv))
        charge = max(0, -bat); discharge = max(0, bat)
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = [ts, soc, BATT.get(status, status), pv, ac, bat, charge,
               discharge, backup, grid, load, ac - bat, pv + bat - ac, soh, pack_v]
        with open(CSV, "a") as f:
            f.write(",".join(str(x) for x in row) + "\n")
        if status != last_status:
            print(f"{ts}  STATUS -> {BATT.get(status, status)}  soc={soc} charge={charge} ac={ac} backup={backup}", flush=True)
            last_status = status
    except Exception as e:
        print(f"{datetime.datetime.now():%H:%M:%S} skip ({e})", flush=True)
        try:
            if s:
                s.close()
        except Exception:
            pass
    time.sleep(INTERVAL)
print("sampler done", flush=True)
