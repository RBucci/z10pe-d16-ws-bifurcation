#!/usr/bin/env python3
"""Change the default PCIe bifurcation of a slot in an ASUS Z10PE-D16 WS BIOS capsule.

The stock BIOS (version 4101) contains bifurcation settings for every CPU PCIe
port, but hides them from the setup menu. This script changes the factory
default of one or more of those settings inside the capsule file, by editing
the "IntelSetup" entry of the built-in StdDefaults store. One byte changes per
setting; nothing else in the file is touched.

Usage:
  patch_bifurcation.py show  STOCK.CAP
  patch_bifurcation.py patch STOCK.CAP OUT.CAP --set IIO1.IOU1=x4x4x4x4

Only BIOS 4101 was analysed. Other versions are refused unless --force is given,
and --force is only safe if you have re-derived the offsets for that version
(see tools/ifr_dump.py).
"""
import argparse
import hashlib
import sys

CAP_HEADER = 2048
CAP_SIZE = 16779264
STOCK_4101_SHA256 = "bf8fa903354d9ebf1e19d057b9cb960b169319d757969f197ce44f630c15818f"
VAR_NAME = "IntelSetup"
VAR_SIZE = 0x1672

# Offsets inside the IntelSetup variable, read from the setup definitions (IFR)
# of BIOS 4101. IIO0 is CPU1, IIO1 is CPU2.
OFFSETS = {
    "IIO0.IOU0": 0x532, "IIO0.IOU1": 0x536, "IIO0.IOU2": 0x53A,
    "IIO1.IOU0": 0x533, "IIO1.IOU1": 0x537, "IIO1.IOU2": 0x53B,
}
# IOU0 and IOU1 are 16-lane ports, IOU2 is an 8-lane port.
MODES_X16 = {"x4x4x4x4": 0x00, "x4x4x8": 0x01, "x8x4x4": 0x02, "x8x8": 0x03, "x16": 0x04, "auto": 0xFF}
MODES_X8 = {"x4x4": 0x00, "x8": 0x01, "auto": 0xFF}
STOCK_DEFAULTS = {
    "IIO0.IOU0": 0x04, "IIO0.IOU1": 0x04, "IIO0.IOU2": 0x01,
    "IIO1.IOU0": 0x04, "IIO1.IOU1": 0x04, "IIO1.IOU2": 0x01,
}


def modes_for(port):
    return MODES_X8 if port.endswith("IOU2") else MODES_X16


def mode_name(port, value):
    for name, v in modes_for(port).items():
        if v == value:
            return name
    return "unknown"


def walk_nvar(buf, start, end):
    """Yield (name, entry_offset, data_offset, data_len, attr) for NVAR entries."""
    p = start
    while p + 10 <= end and buf[p:p + 4] == b"NVAR":
        size = int.from_bytes(buf[p + 4:p + 6], "little")
        attr = buf[p + 9]
        if size < 10:
            return
        q = p + 10
        name = ""
        if not attr & 0x08:                      # not a data-only entry
            q += 16 if attr & 0x04 else 1        # full GUID or GUID index
            if attr & 0x02:                      # ASCII name
                e = buf.index(b"\0", q)
                name = buf[q:e].decode("ascii", "replace")
                q = e + 1
            else:                                # UTF-16 name
                e = q
                while buf[e:e + 2] != b"\0\0":
                    e += 2
                name = buf[q:e].decode("utf-16le", "replace")
                q = e + 2
        yield name, p, q, p + size - q, attr
        p += size


def find_variable(cap):
    """Return the capsule offset of the IntelSetup data inside StdDefaults."""
    outer = cap.find(b"NVAR", CAP_HEADER)
    while outer != -1:
        for name, entry, data, length, attr in walk_nvar(cap, outer, outer + 16):
            if name == "StdDefaults":
                for n2, e2, d2, l2, a2 in walk_nvar(cap, data, data + length):
                    if n2 == VAR_NAME:
                        if attr & 0x10 or a2 & 0x10:
                            sys.exit("This store uses extended NVAR headers (checksums). Not supported.")
                        if l2 != VAR_SIZE:
                            sys.exit(f"{VAR_NAME} is {l2:#x} bytes, expected {VAR_SIZE:#x}. Different BIOS layout.")
                        return d2
        outer = cap.find(b"NVAR", outer + 4)
    sys.exit(f"Could not find {VAR_NAME} inside StdDefaults.")


def load(path, force):
    cap = bytearray(open(path, "rb").read())
    digest = hashlib.sha256(cap).hexdigest()
    if digest != STOCK_4101_SHA256:
        msg = (f"{path} is not the stock 4101 capsule (sha256 {digest}).")
        if not force:
            sys.exit(msg + " Refusing; use --force only if you verified the offsets for this file.")
        print("WARNING: " + msg, file=sys.stderr)
    if len(cap) != CAP_SIZE and not force:
        sys.exit(f"Unexpected file size {len(cap)}.")
    return cap


def show(cap, base):
    for port in sorted(OFFSETS):
        v = cap[base + OFFSETS[port]]
        print(f"  {port}  offset {OFFSETS[port]:#05x}  value {v:#04x}  ({mode_name(port, v)})")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("show", help="print the bifurcation defaults stored in a capsule")
    s.add_argument("cap")
    s.add_argument("--force", action="store_true")
    p = sub.add_parser("patch", help="write a capsule with changed defaults")
    p.add_argument("cap")
    p.add_argument("out")
    p.add_argument("--set", action="append", required=True, metavar="PORT=MODE",
                   help="for example IIO1.IOU1=x4x4x4x4 (repeatable)")
    p.add_argument("--force", action="store_true")
    a = ap.parse_args()

    cap = load(a.cap, a.force)
    base = find_variable(cap)
    print(f"{VAR_NAME} defaults found at capsule offset {base:#x}")
    if a.cmd == "show":
        show(cap, base)
        return

    original = bytes(cap)
    for item in a.set:
        port, _, mode = item.partition("=")
        port, mode = port.upper(), mode.lower()
        if port not in OFFSETS:
            sys.exit(f"Unknown port {port}. Choose from: {', '.join(sorted(OFFSETS))}")
        if mode not in modes_for(port):
            sys.exit(f"Unknown mode {mode} for {port}. Choose from: {', '.join(modes_for(port))}")
        pos = base + OFFSETS[port]
        if cap[pos] != STOCK_DEFAULTS[port] and not a.force:
            sys.exit(f"{port} holds {cap[pos]:#04x}, expected stock value {STOCK_DEFAULTS[port]:#04x}.")
        cap[pos] = modes_for(port)[mode]
        print(f"  {port}: {original[pos]:#04x} -> {cap[pos]:#04x} ({mode}) at capsule offset {pos:#x}")

    changed = [i for i in range(len(cap)) if cap[i] != original[i]]
    allowed = {base + o for o in OFFSETS.values()}
    if not set(changed) <= allowed:
        sys.exit("Internal error: bytes outside the bifurcation settings changed. Nothing written.")
    open(a.out, "wb").write(cap)
    print(f"{len(changed)} byte(s) changed. Wrote {a.out}")
    print(f"sha256 {hashlib.sha256(cap).hexdigest()}")
    show(cap, base)


if __name__ == "__main__":
    main()
