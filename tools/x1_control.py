#!/usr/bin/env python3
"""Anker SOLIX X1 — 'discharge on need' controller.

Closed loop targeting grid power = 0: the battery discharges just enough to
cover house load, without importing or exporting. Discharge-only (never
charges); respects an SOC floor; keeps the VPP watchdog fed; always restores
the original work mode on exit.

Usage:
  python3 x1_control.py        # DRY RUN (reads + prints, NO writes)
  python3 x1_control.py go     # LIVE (commands the battery)
"""
import socket, struct, time, sys, signal, datetime

HOST, PORT, UNIT, TIMEOUT = "192.168.1.100", 502, 1, 2.0

MIN_SOC        = 10      # %   don't discharge below this
MAX_DISCHARGE  = 5000    # W   cap on commanded discharge
TARGET_GRID    = 0       # W   aim for zero grid flow
DEADBAND       = 40      # W   ignore tiny grid errors (anti-jitter)
GAIN           = 0.8     # correction damping (0..1)
WATCHDOG_S     = 30      # s   short safety watchdog while controlling
INTERVAL_S     = 3       # s   loop period
RESTORE_MODE   = 20      # work mode to restore on exit

LIVE = len(sys.argv) > 1 and sys.argv[1].lower() == "go"
STATUS = {0: "Standby", 1: "Charging", 2: "Discharging", 3: "Sleep"}


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
        self.s.sendall(struct.pack(">HHHB", want, 0, len(pdu) + 1, UNIT) + pdu)
        body = None
        for _ in range(8):
            hdr = self._recv(7)
            tid, _, length, _ = struct.unpack(">HHHB", hdr)
            body = self._recv(length - 1)
            if tid == want:
                break
        if body[0] & 0x80:
            raise RuntimeError(f"modbus exc fc={body[0]:#x} code={body[1]}")
        return body
    def read(self, fc, addr, count):
        body = self._txn(struct.pack(">BHH", fc, addr, count))
        bc = body[1]
        return list(struct.unpack(">%dH" % (bc // 2), body[2:2 + bc]))
    def write_single(self, addr, val):
        self._txn(struct.pack(">BHH", 0x06, addr, val & 0xFFFF))
    def write_multi(self, addr, words):
        pdu = struct.pack(">BHHB", 0x10, addr, len(words), len(words) * 2)
        pdu += b"".join(struct.pack(">H", w & 0xFFFF) for w in words)
        self._txn(pdu)


def le32(w):                       # little-endian word order INT32
    return struct.unpack(">i", struct.pack(">HH", w[1], w[0]))[0]

def le32_words(val):               # signed int -> [lo_word, hi_word]
    b = struct.pack("<i", val)
    return [struct.unpack("<H", b[0:2])[0], struct.unpack("<H", b[2:4])[0]]

def stamp():
    return datetime.datetime.now().strftime("%H:%M:%S")


def read_state(mb):
    s = mb.read(0x04, 10001, 15)               # 10001..10015 block
    return {
        "status": s[0],
        "batt":   le32([s[7], s[8]]),           # 10008  +disch / -charge
        "load":   le32([s[9], s[10]]),          # 10010  house load
        "grid":   le32([s[11], s[12]]),         # 10012  +import / -export
        "soc":    s[13],                        # 10014
    }


def main():
    mb = MB()
    orig_wm = mb.read(0x03, 10064, 1)[0]
    orig_wd = mb.read(0x03, 10080, 1)[0]
    print(f"mode={'LIVE' if LIVE else 'DRY-RUN'}  orig work mode={orig_wm}  "
          f"watchdog={orig_wd}s  (Ctrl-C to stop & restore)", flush=True)

    engaged = False
    cmd = 0  # current discharge setpoint (W, >=0)

    def restore(*_):
        if LIVE and engaged:
            try:
                mb.write_multi(10071, le32_words(0))
                mb.write_single(10064, orig_wm)
                mb.write_single(10080, orig_wd)
                print(f"\n[restore] 10071->0, 10064->{orig_wm}, 10080->{orig_wd}s", flush=True)
            except Exception as e:
                print(f"\n[restore] error: {e}; watchdog reverts in <={WATCHDOG_S}s", flush=True)
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, restore)
    try:
        while True:
            st = read_state(mb)
            grid = st["grid"]

            if st["soc"] <= MIN_SOC:
                new_cmd = 0
                reason = f"SOC {st['soc']}%<=floor"
            elif abs(grid - TARGET_GRID) <= DEADBAND:
                new_cmd = cmd
                reason = "in deadband"
            else:
                # grid>0 (importing) -> discharge more; grid<0 (export) -> less
                new_cmd = cmd + int(GAIN * (grid - TARGET_GRID))
                new_cmd = max(0, min(MAX_DISCHARGE, new_cmd))
                reason = "tracking grid->0"

            act = "WOULD WRITE" if not LIVE else "WRITE"
            print(f"[{stamp()}] grid={grid:+5d}W load={st['load']:5d}W "
                  f"batt={st['batt']:+5d}W SOC={st['soc']}% st={STATUS.get(st['status'],'?')[:4]} "
                  f"| {act} discharge={new_cmd}W ({reason})", flush=True)

            if LIVE:
                if not engaged:
                    mb.write_single(10080, WATCHDOG_S)
                    mb.write_single(10064, 3)
                    engaged = True
                mb.write_multi(10071, le32_words(new_cmd))
            cmd = new_cmd
            time.sleep(INTERVAL_S)
    except (KeyboardInterrupt, SystemExit):
        restore()


if __name__ == "__main__":
    main()
