#!/usr/bin/env python3
"""Read-only Modbus TCP scanner for the Anker SOLIX X1.

Safety: this script ONLY issues function codes 0x03 (read holding) and
0x04 (read input). There is no write path anywhere. It cannot change the
device. Goal: find live-but-undocumented registers ("hidden features").
"""
import socket, struct, sys, time, json

HOST = "192.168.1.100"
PORT = 502
UNIT = 1
TIMEOUT = 2.0

EXC = {1: "IllegalFunction", 2: "IllegalDataValue", 3: "IllegalAddress",
       4: "DeviceFailure", 5: "Ack", 6: "Busy"}


class MB:
    def __init__(self, host, port, unit):
        self.host, self.port, self.unit = host, port, unit
        self.tid = 0
        self.s = None
        self.connect()

    def connect(self):
        if self.s:
            try: self.s.close()
            except Exception: pass
        self.s = socket.create_connection((self.host, self.port), timeout=TIMEOUT)
        self.s.settimeout(TIMEOUT)

    def _recv(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.s.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("closed")
            buf += chunk
        return buf

    def read(self, fc, addr, count):
        """Return ('ok', list[regvals]) or ('err', exc_code) or ('to', None)."""
        self.tid = (self.tid + 1) & 0xFFFF
        pdu = struct.pack(">BHH", fc, addr, count)
        mbap = struct.pack(">HHHB", self.tid, 0, len(pdu) + 1, self.unit)
        try:
            self.s.sendall(mbap + pdu)
            hdr = self._recv(7)
            _, _, length, _ = struct.unpack(">HHHB", hdr)
            body = self._recv(length - 1)
        except (socket.timeout, ConnectionError, OSError):
            try: self.connect()
            except Exception: pass
            return ("to", None)
        rfc = body[0]
        if rfc & 0x80:
            return ("err", body[1])
        bc = body[1]
        data = body[2:2 + bc]
        regs = list(struct.unpack(">%dH" % (bc // 2), data)) if bc else []
        return ("ok", regs)


def sweep(mb, lo, hi, fc=0x04, block=8, label=""):
    """Coarse block sweep. Returns dict addr->value for responsive registers.

    Adaptive: counts consecutive timeouts. If a region just stops answering
    (device ignores invalid addresses instead of erroring), bail early so we
    don't spend minutes hammering dead address space.
    """
    live = {}
    addr = lo
    timeouts = 0
    errs = 0
    while addr <= hi:
        n = min(block, hi - addr + 1)
        kind, payload = mb.read(fc, addr, n)
        if kind == "ok":
            timeouts = 0
            for i, v in enumerate(payload):
                live[addr + i] = v
        elif kind == "err":
            errs += 1
            timeouts = 0
        elif kind == "to":
            timeouts += 1
            if timeouts >= 12:  # ~24s of silence => region is dead, stop
                print(f"  [{label}] gave up at {addr} after {timeouts} timeouts", flush=True)
                break
        if (addr - lo) % 512 == 0:
            print(f"  [{label}] at {addr}, live={len(live)}, errs={errs}", flush=True)
        addr += n
    return live


def main():
    mb = MB(HOST, PORT, UNIT)

    # --- 1. Sanity check against documented registers ---
    print("=== Sanity check (documented) ===")
    checks = [(10000, "Plant Status", 0x04), (10001, "Battery Status", 0x04),
              (10014, "SOC %", 0x04), (10015, "SOH %", 0x04),
              (10064, "Work Mode (RW)", 0x03)]
    for addr, name, fc in checks:
        kind, payload = mb.read(fc, addr, 1)
        print(f"  {addr} {name:18} fc{fc:#04x} -> {kind} {payload}")

    # --- 2. Map documented extent + reserved gaps (10000..10700) ---
    print("\n=== Scanning documented + reserved (10000-10700, fc04) ===")
    doc = sweep(mb, 10000, 10700, fc=0x04, block=16, label="doc")
    print(f"  responsive registers: {len(doc)}")

    # --- 3. Probe UNDOCUMENTED ranges ---
    print("\n=== Probing undocumented low range (0-9999, fc04) ===")
    low = sweep(mb, 0, 9999, fc=0x04, block=8, label="low")
    print(f"  responsive registers: {len(low)}")

    print("\n=== Probing undocumented high range (10701-13000, fc04) ===")
    high = sweep(mb, 10701, 13000, fc=0x04, block=8, label="high")
    print(f"  responsive registers: {len(high)}")

    # --- 4. Save everything ---
    out = {"doc_10000_10700": doc, "low_0_9999": low, "high_10701_13000": high}
    with open("/Users/kleist/Sites/anker-x1-scan/scan_result.json", "w") as f:
        json.dump({k: {str(a): v for a, v in d.items()} for k, d in out.items()}, f, indent=2)

    # --- 5. Highlight non-zero registers OUTSIDE documented address blocks ---
    print("\n=== Non-zero registers in UNDOCUMENTED ranges (candidates) ===")
    cand = {a: v for a, v in {**low, **high}.items() if v != 0}
    for a in sorted(cand):
        print(f"  {a}: {cand[a]}  (0x{cand[a]:04x})")
    if not cand:
        print("  none (undocumented ranges read as 0 or not present)")

    print(f"\nSaved full dump -> scan_result.json")


if __name__ == "__main__":
    main()
