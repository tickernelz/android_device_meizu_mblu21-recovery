#!/usr/bin/env python3
"""Replace the AVB blob inside a built vendor_boot image with the stock Meizu one.

The mBlu 21 bootloader only boots a vendor_boot whose embedded vbmeta carries the
Meizu chain key (sha1 4fce36c7..., rollback index 1790812800); a test-key blob stops at
the logo. The ramdisk, DTB, cmdline and bootconfig stay exactly as built.

The partition layout after the image data is [vbmeta blob][footer]. A build may reserve
a slightly larger blob than the stock one (OrangeFox: 2304 vs 2240 bytes), so the stock
blob is written first and the remaining reserved bytes are zeroed.
"""

import argparse
import hashlib
import struct

FOOTER_SIZE = 64
MAGIC = b"AVBf"


def parse(blob):
    footer = blob[-FOOTER_SIZE:]
    if footer[:4] != MAGIC:
        raise SystemExit("no AVB footer in vendor_boot image")
    major, minor = struct.unpack(">II", footer[4:12])
    if (major, minor) != (1, 0):
        raise SystemExit(f"unsupported AVB footer version {major}.{minor}")
    return struct.unpack(">QQQ", footer[12:36])


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--stock-vbmeta", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report")
    args = parser.parse_args()

    blob = bytearray(open(args.image, "rb").read())
    stock = open(args.stock_vbmeta, "rb").read()
    original_size, vbmeta_offset, reserved = parse(bytes(blob))
    if vbmeta_offset != original_size:
        raise SystemExit(
            f"vbmeta blob at {vbmeta_offset} does not follow the image end {original_size}")
    if len(stock) > reserved:
        raise SystemExit(
            f"stock vbmeta is {len(stock)} bytes but the image reserves only {reserved}")
    if original_size + reserved + FOOTER_SIZE > len(blob):
        raise SystemExit("image data, vbmeta blob and footer do not fit the partition")

    replaced = sha256(bytes(blob[vbmeta_offset:vbmeta_offset + reserved]))
    blob[vbmeta_offset:vbmeta_offset + reserved] = stock + bytes(reserved - len(stock))
    open(args.output, "wb").write(bytes(blob))

    lines = [
        f"image_size {len(blob)}",
        f"image_data {original_size}",
        f"vbmeta_offset {vbmeta_offset}",
        f"vbmeta_reserved {reserved}",
        f"vbmeta_written {len(stock)}",
        f"vbmeta_replaced_sha256 {replaced}",
        f"vbmeta_stock_sha256 {sha256(stock)}",
        f"output_sha256 {sha256(bytes(blob))}",
    ]
    if args.report:
        open(args.report, "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
