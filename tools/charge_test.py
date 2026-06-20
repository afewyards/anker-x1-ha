#!/usr/bin/env python3
"""1 kW charge test for Anker SOLIX X1 — live write, with safety + auto-restore.

Sequence:
  1. read baseline (work mode, watchdog, soc, batt power, status)
  2. set VPP watchdog SHORT (60s) so device self-reverts if we vanish
  3. enter work mode 3 (3rd-party/VPP control)
  4. command 10071 = -1000 W (charge), VERIFY readback == -1000 else abort
  5. observe ~30s (re-asserting command each loop to feed watchdog)
  6. finally: idle (10071=0) -> restore original work mode + watchdog
"""
import socket, struct, time, datetime

HOST, PORT, UNIT, TIMEOUT = "192.168.1.100", 502, 1, 2.0


class MB:
    def __init__(self):
        self.tid = 0; self.s = None; self.connect()
    def connect(self):
        if self.s:
            try: self.s.close()
            except Exception: pass
        self.s = socket.create_connection((HOST, PORT), timeout=TIMEOUT)
        self.s.settimeout(TIMEOUT)
    def _recv(self, n):
        b = b""
        while len(b) < n:
            c = self.s.recv(n - len(b))
            if not c: raise ConnectionError("closed")
            b += c
        return b
    def _txn(self, pdu):
        self.tid = (self.tid + 1) & 0xFFFF
        want = self.tid
        mbap = struct.pack(">HHHB", want, 0, len(pdu) + 1, UNIT)
        self.s.sendall(mbap + pdu)
        for _ in range(8):  # discard stale/mismatched responses (TID match)
            hdr = self._recv(7)
            tid, _, length, _ = struct.unpack(">HHHB", hdr)
            body = self._recv(length - 1)
            if tid == want:
                break
        if body[0] & 0x80:
            raise RuntimeError(f"modbus exception fc={body[0]:#x} code={body[1]}")
        return body
    def read(self, fc, addr, count):
        body = self._txn(struct.pack(">BHH", fc, addr, count))
        bc = body[1]
        return list(struct.unpack(">%dH" % (bc // 2), body[2:2 + bc]))
    def write_single(self, addr, val):  # FC 0x06
        self._txn(struct.pack(">BHH", 0x06, addr, val & 0xFFFF))
    def write_multi(self, addr, words):  # FC 0x10
        pdu = struct.pack(">BHHB", 0x10, addr, len(words), len(words) * 2)
        pdu += b"".join(struct.pack(">H", w & 0xFFFF) for w in words)
        self._txn(pdu)


def be32(w):  # big-endian word order (hi, lo)
    return struct.unpack(">i", struct.pack(">HH", w[0], w[1]))[0]


def le32(w):  # little-endian word order (lo, hi) — what the X1 uses for 10071
    return struct.unpack(">i", struct.pack(">HH", w[1], w[0]))[0]


def le32_words(val):  # encode signed int -> [lo_word, hi_word]
    b = struct.pack("<i", val)
    return [struct.unpack("<H", b[0:2])[0], struct.unpack("<H", b[2:4])[0]]


def i32(hi, lo):
    return struct.unpack(">i", struct.pack(">HH", hi, lo))[0]


def stamp():
    return datetime.datetime.now().strftime("%H:%M:%S")


STATUS = {0: "Standby", 1: "Charging", 2: "Discharging", 3: "Sleep"}


def snapshot(mb, tag):
    s = mb.read(0x04, 10001, 15)            # 10001..10015
    status = s[0]
    bp_be = i32(s[7], s[8])                  # 10008/09 batt power, big-endian
    bp_le = le32([s[7], s[8]])               # ... little-endian (for comparison)
    soc = s[13]                              # 10014
    wm = mb.read(0x03, 10064, 1)[0]
    cmd = le32(mb.read(0x03, 10071, 2))      # 10071/72 command readback (LE)
    print(f"  [{stamp()}] {tag:9} status={status}({STATUS.get(status,'?')}) "
          f"battPower[BE={bp_be:+} LE={bp_le:+}]W SOC={soc}% workmode={wm} "
          f"cmd10071={cmd:+}W", flush=True)
    return wm


def main():
    mb = MB()
    print("=== BASELINE ===", flush=True)
    orig_wm = mb.read(0x03, 10064, 1)[0]
    orig_wd = mb.read(0x03, 10080, 1)[0]
    print(f"  original work mode 10064 = {orig_wm}", flush=True)
    print(f"  original watchdog  10080 = {orig_wd}s", flush=True)
    snapshot(mb, "before")

    try:
        print("\n=== ENGAGE ===", flush=True)
        mb.write_single(10080, 60)          # short watchdog safety net
        print("  watchdog 10080 -> 60s", flush=True)
        mb.write_single(10064, 3)           # VPP / 3rd-party control
        print("  work mode 10064 -> 3 (VPP control)", flush=True)
        charge_cmd = le32_words(-1000)      # -1000 W, little-endian word order
        mb.write_multi(10071, charge_cmd)
        rb = le32(mb.read(0x03, 10071, 2))
        print(f"  command 10071 -> -1000W (words={charge_cmd}), readback = {rb:+}W", flush=True)
        if rb != -1000:
            print("  !! readback mismatch — ABORTING test", flush=True)
            return

        print("\n=== OBSERVE (~30s) ===  expect ~1kW charge", flush=True)
        for _ in range(10):
            mb.write_multi(10071, charge_cmd)  # re-assert (feed watchdog)
            snapshot(mb, "charging")
            time.sleep(3)
    finally:
        print("\n=== RESTORE ===", flush=True)
        try:
            mb.write_multi(10071, [0, 0])            # idle
            print("  10071 -> 0 (idle)", flush=True)
            mb.write_single(10064, orig_wm)          # original mode
            print(f"  10064 -> {orig_wm} (restored)", flush=True)
            mb.write_single(10080, orig_wd)          # original watchdog
            print(f"  10080 -> {orig_wd}s (restored)", flush=True)
            time.sleep(2)
            snapshot(mb, "after")
        except Exception as e:
            print(f"  !! restore error: {e} — watchdog will revert in <=60s", flush=True)


if __name__ == "__main__":
    main()
