# PCIe bifurcation on the ASUS Z10PE-D16 WS (BIOS 4101)

The ASUS Z10PE-D16 WS has no menu option to split a PCIe slot, so a passive
multi-drive M.2 card (ASUS Hyper M.2 and similar) only shows its first SSD.
The settings exist in the BIOS; they are hidden. This repository documents
where they live and provides a script that changes the factory default of a
chosen port inside the official BIOS file. The change is one byte per port.

No BIOS files are distributed here. The script patches the file you download
from ASUS, and the result can be checked against the hashes below.

## Status

Tested on one board. Treat everything outside "What was tested" as unproven.

**What was tested**

- Board: Z10PE-D16 WS, BIOS 4101, two Xeon E5-2640 v4.
- Card: two-slot ASUS ROG Hyper M.2 card on CPU2 port 3 (`80:03.0` in `lspci`).
- Change: `IIO1.IOU1` from x16 to x4x4x4x4.
- Flashed with EZ Flash from the BIOS. The board accepted the modified capsule.
- Result: both NVMe drives on the card were detected by Linux (Proxmox VE).
  First a Crucial P3 2 TB with a Lexar NM620 512 GB, then the Crucial with a
  WD_BLACK SN770M 1 TB (M.2 2230).

**What was not tested**

- Any port other than `IIO1.IOU1`, and any mode other than x4x4x4x4.
- Flashing this file with USB BIOS Flashback.
- Whether "Load Optimized Defaults" (F5) in setup puts the port back to x16.
  The menu definitions still carry x16 as their default, so it may.
- BIOS versions other than 4101. The script refuses them.

## How the setting is stored

The hidden options belong to the `IntelRCSetup` form set and are stored in the
UEFI variable `IntelSetup` (GUID `ec87d643-eba4-4bb5-a1e5-3f3e36b20da9`, size
`0x1672`). Each port is one byte:

| Port | Root port (lspci) | Offset | Stock default | Lanes |
|---|---|---|---|---|
| `IIO0.IOU2` (CPU1 port 1) | `00:01.0` | `0x53A` | `0x01` x8 | 8 |
| `IIO0.IOU0` (CPU1 port 2) | `00:02.0` | `0x532` | `0x04` x16 | 16 |
| `IIO0.IOU1` (CPU1 port 3) | `00:03.0` | `0x536` | `0x04` x16 | 16 |
| `IIO1.IOU2` (CPU2 port 1) | `80:01.0` | `0x53B` | `0x01` x8 | 8 |
| `IIO1.IOU0` (CPU2 port 2) | `80:02.0` | `0x533` | `0x04` x16 | 16 |
| `IIO1.IOU1` (CPU2 port 3) | `80:03.0` | `0x537` | `0x04` x16 | 16 |

Values for the 16-lane ports: `0x00` x4x4x4x4, `0x01` x4x4x8, `0x02` x8x4x4,
`0x03` x8x8, `0x04` x16, `0xFF` Auto. Values for the 8-lane ports: `0x00` x4x4,
`0x01` x8, `0xFF` Auto.

The offsets, values and the "IOUn is port n" naming come from the setup
definitions in BIOS 4101 (see `tools/ifr_dump.py`). The root port column was
confirmed on the test board only for `80:03.0`; the others follow the same
numbering and are not individually verified.

For the mapping from these ports to the six physical slots, see
[breadlam's notes](https://github.com/breadlam/Asus-Z10PE-D16-WS-Stuff). It is
easier and safer to read the root port from `lspci` than to rely on a slot map.

The BIOS image also holds a copy of every setup variable's factory defaults, in
an NVAR entry named `StdDefaults` at the start of the NVRAM volume (image offset
`0x800000`). The `IntelSetup` defaults sit at image offset `0x800273`. These
entries have no checksum, the enclosing file uses the fixed `0xAA` data
checksum, and the volume header checksum covers the header only. So changing a
default there needs no other adjustment. That is the whole modification.

## Steps to reproduce

You need Python 3. The script uses only the standard library.

**1. Find the root port of your M.2 card** (Linux, card installed with at least
one drive):

```
lspci -tv | grep -B3 -i -E "nvme|non-volatile"
```

Match the root port (`80:03.0` and so on) to the table above.

**2. Check that your board is on BIOS 4101 with stock values** (optional, Linux
booted in UEFI mode). The variable cannot be seeked, so copy it with `cat`:

```
cat /sys/firmware/efi/efivars/IntelSetup-ec87d643-eba4-4bb5-a1e5-3f3e36b20da9 > IntelSetup.bak
od -A x -t x1 -j $((4+0x532)) -N 12 IntelSetup.bak
```

A stock board prints `04 04 ff ff 04 04 ff ff 01 01 ff ff`. The file is 5750
bytes: 4 bytes of attributes followed by the variable.

**3. Download BIOS 4101 from ASUS** and unzip it:

<https://dlcdnets.asus.com/pub/ASUS/mb/Socket2011-R3/Z10PE-D16_WS/BIOS/Z10PE-D16-WS-ASUS-4101.zip>

`Z10PE-D16-WS-ASUS-4101.CAP` must have this SHA-256:

```
bf8fa903354d9ebf1e19d057b9cb960b169319d757969f197ce44f630c15818f
```

**4. Patch it:**

```
python3 patch_bifurcation.py show  Z10PE-D16-WS-ASUS-4101.CAP
python3 patch_bifurcation.py patch Z10PE-D16-WS-ASUS-4101.CAP modified.CAP --set IIO1.IOU1=x4x4x4x4
```

`--set` can be repeated for several ports. For the tested change above, the
output file has this SHA-256:

```
538f459fda20193558a0a03eeb149127c3cb9c5362e72335ea5688851e668b90
```

It differs from the stock file in one byte, at capsule offset `0x800FAA`
(`0x04` to `0x00`).

**5. Flash `modified.CAP`.** EZ Flash from the BIOS setup accepted it on the
test board. According to breadlam's notes the board does not verify the capsule
signature, and USB BIOS Flashback accepts modified files when they are named
`Z1016WS.CAP`; that route was not tested here.

**6. Put all drives in the card, boot, and check:**

```
lspci -tv | grep -i -E "nvme|non-volatile"
lsblk -d -o NAME,SIZE,MODEL
```

If only one drive appears, the previously saved settings may have survived the
flash. Clearing the CMOS should make the board load the new defaults. This is
untested.

BIOS settings return to their defaults after flashing. Set them again, and
avoid "Load Optimized Defaults" until someone confirms what it does to the
hidden setting.

## Recovery

Flash the unmodified `Z10PE-D16-WS-ASUS-4101.CAP` again. The board has USB BIOS
Flashback, which works without a bootable BIOS. Keep a FAT32 stick with the
stock file ready before you start.

## What did not work

Writing the variable from a running Linux system. With the immutable flag
removed (`chattr -i`), rewriting `IntelSetup` through efivarfs with only offset
`0x537` changed fails with `EINVAL`, and the variable is left unchanged. The
firmware rejects the runtime write.

Changing it from a UEFI shell with
[setup_var.efi](https://github.com/datasone/setup_var.efi) was not tried:

```
setup_var.efi IntelSetup:0x537=0x00
```

If that works on this board it would avoid flashing altogether. Reports welcome.

## How the offsets were found

```
dd if=Z10PE-D16-WS-ASUS-4101.CAP of=bios.bin bs=2048 skip=1
pip install uefi_firmware
uefi-firmware-parser -b -e -o out bios.bin
python3 tools/ifr_dump.py out IOU
```

The capsule is a 2048-byte header followed by the 16 MB flash image.
`tools/ifr_dump.py` finds the Setup module in the unpacked tree and prints each
matching question with its variable, offset, options and default. The
bifurcation questions are printed as "inside suppress-if", which is why they
never appear in the menu.

## Credits

- [breadlam/Asus-Z10PE-D16-WS-Stuff](https://github.com/breadlam/Asus-Z10PE-D16-WS-Stuff)
  and the overclock.net Z10PE-D16 WS owners thread, for the capsule layout, the
  finding that the signature is not checked, and the slot map.
- Analysis and scripts written with Claude.

## Disclaimer

Flashing a modified BIOS can leave a board unable to start. This worked on one
board and comes with no warranty. You do this at your own risk.
