#!/usr/bin/env python3
"""Print setup questions (name, variable, offset, options, defaults) from an AMI Setup module.

This is how the offsets in patch_bifurcation.py were found. Unpack the BIOS first:

  dd if=Z10PE-D16-WS-ASUS-4101.CAP of=bios.bin bs=2048 skip=1
  pip install uefi_firmware
  uefi-firmware-parser -b -e -o out bios.bin
  python3 tools/ifr_dump.py out IOU

The first argument is the unpacked directory (the Setup module is found by its
strings) or the Setup PE file itself. Remaining arguments are case-insensitive
filters on the question name; with none, every one-of question is printed.
"""
import os
import struct
import sys
import uuid


def find_setup(path):
    if os.path.isfile(path):
        return path
    for d, _, files in os.walk(path):
        for f in files:
            p = os.path.join(d, f)
            if not p.endswith(".pe"):
                continue
            b = open(p, "rb").read()
            if "IntelRCSetup".encode("utf-16le") in b and "IOU0".encode("utf-16le") in b:
                return p
    sys.exit("Setup module not found under " + path)


def read_strings(b):
    """Parse the largest en-US HII string package."""
    cands, pos = [], 0
    while True:
        i = b.find(b"en-US\x00", pos)
        if i < 0:
            break
        pos = i + 1
        h = i - 46
        if h >= 0 and b[h + 3] == 0x04:
            ln = int.from_bytes(b[h:h + 3], "little")
            if 0x30 < ln < len(b):
                cands.append((ln, h))
    if not cands:
        sys.exit("No string package found")
    ln, h = max(cands)
    p = h + struct.unpack_from("<I", b, h + 4)[0]
    end, sid, out = h + ln, 1, {}
    while p < end:
        t = b[p]
        if t == 0x00:
            break
        if t in (0x14, 0x15):
            q = p + (1 if t == 0x14 else 2)
            s = q
            while b[q:q + 2] != b"\0\0":
                q += 2
            out[sid] = b[s:q].decode("utf-16le", "replace")
            sid += 1
            p = q + 2
        elif t == 0x21:
            sid += b[p + 1]
            p += 2
        elif t == 0x22:
            sid += struct.unpack_from("<H", b, p + 1)[0]
            p += 3
        elif t == 0x30:
            p += b[p + 2]
        elif t == 0x31:
            p += struct.unpack_from("<H", b, p + 2)[0]
        elif t == 0x32:
            p += struct.unpack_from("<I", b, p + 2)[0]
        else:
            print(f"unknown string block {t:#x} at {p:#x}", file=sys.stderr)
            break
    return out


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    path = find_setup(sys.argv[1])
    want = [w.lower() for w in sys.argv[2:]]
    b = open(path, "rb").read()
    strings = read_strings(b)
    S = lambda n: strings.get(n, "<%d>" % n)
    print("module:", path)

    packages = []
    for i in range(4, len(b) - 40):
        if b[i] == 0x0E and b[i + 1] & 0x80 and (b[i + 1] & 0x7F) >= 0x18 and b[i - 1] == 0x02:
            ln = int.from_bytes(b[i - 4:i - 1], "little")
            if 0x40 < ln < len(b) - i:
                packages.append((i - 4, ln))

    for base, ln in packages:
        p, end, stack, stores, form, cur = base + 4, base + ln, [], {}, None, None
        while p < end:
            op, length, scope = b[p], b[p + 1] & 0x7F, b[p + 1] >> 7
            if length < 2:
                break
            d = b[p:p + length]
            if op == 0x0E:
                print("\nFormSet", S(struct.unpack_from("<H", d, 18)[0]), uuid.UUID(bytes_le=bytes(d[2:18])))
            elif op == 0x24:
                vid, size = struct.unpack_from("<HH", d, 18)
                name = d[22:].split(b"\0")[0].decode()
                stores[vid] = name
                print(f"  VarStore {vid:#x} {name} guid {uuid.UUID(bytes_le=bytes(d[2:18]))} size {size:#x}")
            elif op == 0x26:
                vid = struct.unpack_from("<H", d, 2)[0]
                size = struct.unpack_from("<H", d, 24)[0]
                name = d[26:].split(b"\0")[0].decode()
                stores[vid] = name
                print(f"  VarStoreEfi {vid:#x} {name} guid {uuid.UUID(bytes_le=bytes(d[4:20]))} size {size:#x}")
            elif op == 0x01:
                fid, title = struct.unpack_from("<HH", d, 2)
                form = (fid, S(title))
            elif op == 0x05:
                prompt, help_, qid, vid, off, _flags = struct.unpack_from("<HHHHHB", d, 2)
                name = S(prompt)
                cur = None
                if not want or any(w in name.lower() for w in want):
                    cur = name
                    hidden = "inside suppress-if" if 0x0A in stack else "visible"
                    print(f"\n  '{name}' | form {form} | {stores.get(vid, '?')} offset {off:#x} | {hidden}")
                    print("     help:", S(help_)[:120].replace("\n", " "))
            elif op == 0x09 and cur:
                sid, flags, _type = struct.unpack_from("<HBB", d, 2)
                val = int.from_bytes(d[6:length], "little")
                print(f"     {S(sid):<12} = {val:#x}{'  (default)' if flags & 0x10 else ''}")
            if op == 0x29:
                if stack and stack.pop() == 0x05:
                    cur = None
            elif scope:
                stack.append(op)
            p += length


if __name__ == "__main__":
    main()
