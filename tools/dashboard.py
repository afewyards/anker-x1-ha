#!/usr/bin/env python3
"""Human-readable live dashboard for the Anker SOLIX X1 (read-only, FC 0x04/0x03).
Decodes the documented register map with correct gain/sign/word-order."""
import socket, struct

HOST, PORT, UNIT, TIMEOUT = "192.168.1.100", 502, 1, 2.0


class MB:
    def __init__(self):
        self.tid = 0; self.s = socket.create_connection((HOST, PORT), timeout=TIMEOUT)
        self.s.settimeout(TIMEOUT)
    def _recv(self, n):
        b = b""
        while len(b) < n:
            c = self.s.recv(n - len(b))
            if not c: raise ConnectionError("closed")
            b += c
        return b
    def read(self, fc, addr, count):
        self.tid = (self.tid + 1) & 0xFFFF
        self.s.sendall(struct.pack(">HHHB", self.tid, 0, 6, UNIT) + struct.pack(">BHH", fc, addr, count))
        for _ in range(8):
            tid, _, length, _ = struct.unpack(">HHHB", self._recv(7))
            body = self._recv(length - 1)
            if tid == self.tid: break
        if body[0] & 0x80: return None
        bc = body[1]
        return list(struct.unpack(">%dH" % (bc // 2), body[2:2 + bc]))


R = {}  # address -> raw word

def grab(mb, lo, hi, fc=0x04):
    a = lo
    while a <= hi:
        n = min(100, hi - a + 1)
        r = mb.read(fc, a, n)
        if r:
            for i, v in enumerate(r): R[a + i] = v
        a += n

def u16(a): return R.get(a, 0)
def i16(a):
    v = R.get(a, 0); return v - 0x10000 if v >= 0x8000 else v
def u32(a):  # little-endian word order (low word first)
    return R.get(a, 0) | (R.get(a + 1, 0) << 16)
def i32(a):
    v = u32(a); return v - 0x100000000 if v >= 0x80000000 else v
def s_str(a, n):  # X1 stores strings low-byte-first within each register
    raw = b"".join(struct.pack("<H", R.get(a + i, 0)) for i in range(n))
    return raw.split(b"\x00")[0].decode("ascii", "replace").strip()

def W(a): return f"{i32(a):+,} W"
def kWh(a): return f"{u32(a)/10:,.1f} kWh"

PLANT = {1:"On-grid",2:"Off-grid",3:"Standby",4:"Fault"}
BATT  = {0:"Standby",1:"Charging",2:"Discharging",3:"Sleep"}
WORK  = {0:"Shutdown",1:"On-grid",2:"Off-grid",3:"Standby",4:"Self-check",5:"Fault"}
MODE  = {0:"Self-consumption",1:"TOU",2:"Backup-only",3:"3rd-party/VPP",4:"User-defined",5:"Socket-agg",20:"(app-managed)"}


def main():
    mb = MB()
    for lo, hi in [(10000, 10090), (10090, 10135), (10143, 10157),
                   (10167, 10213), (10249, 10266), (10620, 10665)]:
        grab(mb, lo, hi)

    print("════════ ANKER SOLIX X1 — LIVE ════════")
    print(f"  Plant status     : {PLANT.get(u16(10000),'?')}")
    print(f"  Battery status   : {BATT.get(u16(10001),'?')}")
    print(f"  Work mode (10064): {u16(10064)}  {MODE.get(u16(10064),'')}")
    print(f"  PCS work status  : {WORK.get(u16(10143),'?')}")

    print("\n── Power flow (now) ──")
    print(f"  PV power         : {W(10002)}")
    print(f"  Battery power    : {W(10008)}   (+discharge / -charge)")
    print(f"  Load (house)     : {W(10010)}")
    print(f"  Grid power       : {W(10012)}   (+import / -export)")
    print(f"  AC active power  : {W(10006)}")
    print(f"  Rechargeable     : {W(10036)}     Dischargeable: {W(10038)}")

    print("\n── Battery ──")
    print(f"  SOC / SOH        : {u16(10014)}% / {u16(10015)}%")
    print(f"  Packs            : {u16(10249)}   Rated capacity: {u32(10250)/10:.1f} kWh")
    print(f"  Pack voltage     : {u16(10253)/10:.1f} V   power: {W(10254)}")

    print("\n── Energy counters ──")
    print(f"  PV today/total       : {kWh(10016)} / {kWh(10018)}")
    print(f"  Batt charge t/t      : {kWh(10020)} / {kWh(10022)}")
    print(f"  Load today/total     : {kWh(10024)} / {kWh(10026)}")
    print(f"  Grid bought t/t      : {kWh(10028)} / {kWh(10030)}")
    print(f"  Grid fed-in t/t      : {kWh(10032)} / {kWh(10034)}")

    print("\n── Grid / AC (PCS) ──")
    print(f"  Grid voltage     : {u16(10199)/10:.1f} V    frequency: {u16(10213)/100:.2f} Hz")
    print(f"  Grid current     : {u16(10205)/100:.2f} A   power factor: {i16(10212)/1000:.3f}")
    print(f"  Internal temp    : {i16(10156)/10:.1f} °C")

    print("\n── Smart meter ──")
    print(f"  Meter type/status: {u16(10630)} / {u16(10631)}")
    print(f"  Total active pwr : {W(10644)}")
    print(f"  Freq / PF        : {u16(10649)/100:.2f} Hz / {i16(10648)/1000:.3f}")
    print(f"  Import / Export  : {kWh(10656)} / {kWh(10664)}")

    print("\n── Identity ──")
    print(f"  PCS model        : {s_str(10090,10)!r}")
    print(f"  PCS serial       : {s_str(10100,12)!r}")
    print(f"  Software / HW ver: {s_str(10112,6)!r} / {s_str(10118,6)!r}")
    print(f"  Rated power      : {i32(10124):,} W   MPPTs: {u16(10130)}  strings/MPPT: {u16(10131)}")


if __name__ == "__main__":
    main()
