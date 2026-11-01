#!/usr/bin/env python3
"""Compare a vendor_boot v4 image against the stock reference recorded from the M416H dump."""

import argparse
import hashlib
import json
import os
import struct
import subprocess
import sys

VENDOR_PREFIXES = ("first_stage_ramdisk", "lib/modules")
HEADER_FORMAT = "<8sIIIII2048sI16sIIQIIII"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
TABLE_ENTRY_FORMAT = "<III32s64s"
TABLE_ENTRY_SIZE = struct.calcsize(TABLE_ENTRY_FORMAT)
RECOVERY_MARKERS = {
    "twrp": ("system/bin/recovery", "twres"),
    "orangefox": ("system/bin/recovery", "twres", "FFiles"),
}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def align(value, page):
    return (value + page - 1) // page * page


def is_vendor_path(name):
    return any(name == prefix or name.startswith(prefix + "/") for prefix in VENDOR_PREFIXES)


def read_image(path):
    with open(path, "rb") as handle:
        blob = handle.read()
    fields = struct.unpack_from(HEADER_FORMAT, blob, 0)
    (magic, version, page, kernel_addr, ramdisk_addr, ramdisk_total, cmdline, tags_addr, board,
     header_size, dtb_size, dtb_addr, table_size, table_entries, table_entry_size, bootconfig_size) = fields
    if magic != b"VNDRBOOT":
        raise SystemExit(f"{path}: not a vendor_boot image (magic {magic!r})")
    offset = align(header_size, page)
    ramdisk_blob = blob[offset:offset + ramdisk_total]
    offset += align(ramdisk_total, page)
    dtb = blob[offset:offset + dtb_size]
    offset += align(dtb_size, page)
    table = []
    for index in range(table_entries):
        size, rd_offset, rd_type, name, board_id = struct.unpack_from(
            TABLE_ENTRY_FORMAT, blob, offset + index * table_entry_size)
        table.append({
            "size": size,
            "offset": rd_offset,
            "type": rd_type,
            "name": name.rstrip(b"\0").decode(),
            "board_id": board_id.hex(),
        })
    offset += align(table_size, page)
    bootconfig = blob[offset:offset + bootconfig_size]
    footer = blob[-64:]
    return {
        "file_size": len(blob),
        "header_version": version,
        "page_size": page,
        "kernel_addr": kernel_addr,
        "ramdisk_addr": ramdisk_addr,
        "tags_addr": tags_addr,
        "dtb_addr": dtb_addr,
        "header_size": header_size,
        "vendor_cmdline": cmdline.rstrip(b"\0").decode(),
        "board_name": board.rstrip(b"\0").decode(),
        "vendor_ramdisk_total_size": ramdisk_total,
        "dtb_size": dtb_size,
        "dtb_sha256": sha256(dtb),
        "bootconfig": bootconfig.decode(),
        "bootconfig_size": bootconfig_size,
        "ramdisk_table": table,
        "avb_footer": footer[:4] == b"AVBf",
        "_ramdisk_blob": ramdisk_blob,
    }


def decompress(blob):
    if blob[:6] == b"070701":
        return blob
    for command in (["lz4", "-dc"], ["gzip", "-dc"]):
        result = subprocess.run(command, input=blob, capture_output=True)
        if result.returncode == 0 and result.stdout[:6] == b"070701":
            return result.stdout
    raise SystemExit("vendor ramdisk is neither lz4 nor gzip newc cpio")


def parse_cpio(data):
    entries = []
    offset = 0
    while offset + 110 <= len(data):
        if data[offset:offset + 6] != b"070701":
            if data[offset:offset + 1] == b"\0":
                offset += 1
                continue
            raise SystemExit(f"bad cpio magic at offset {offset}")
        values = [int(data[offset + 6 + 8 * i: offset + 14 + 8 * i], 16) for i in range(13)]
        mode, uid, gid, file_size, name_size = values[1], values[2], values[3], values[6], values[11]
        name_start = offset + 110
        name = data[name_start:name_start + name_size - 1].decode()
        data_start = align(name_start + name_size, 4)
        content = data[data_start:data_start + file_size]
        offset = align(data_start + file_size, 4)
        if name == "TRAILER!!!":
            continue
        entries.append({"name": name, "mode": mode, "uid": uid, "gid": gid, "content": content})
    return entries


def describe_entry(entry):
    kind = entry["mode"] & 0o170000
    record = {"mode": oct(entry["mode"]), "uid": entry["uid"], "gid": entry["gid"]}
    if kind == 0o120000:
        record["link"] = entry["content"].decode()
    elif kind == 0o100000:
        record["sha256"] = sha256(entry["content"])
        record["size"] = len(entry["content"])
    return record


def ramdisk_view(image):
    fragments = []
    entries = []
    for fragment in image["ramdisk_table"]:
        blob = image["_ramdisk_blob"][fragment["offset"]:fragment["offset"] + fragment["size"]]
        parsed = parse_cpio(decompress(blob))
        fragments.append({"name": fragment["name"], "type": fragment["type"], "entries": len(parsed)})
        entries.extend(parsed)
    return fragments, entries


def module_list(entries, name):
    for entry in entries:
        if entry["name"] == f"lib/modules/{name}":
            return [line for line in entry["content"].decode().splitlines() if line]
    return []


def emit_reference(image_path, out_path):
    image = read_image(image_path)
    _, entries = ramdisk_view(image)
    vendor = {entry["name"]: describe_entry(entry) for entry in entries if is_vendor_path(entry["name"])}
    reference = {key: value for key, value in image.items() if not key.startswith("_")}
    reference["partition_size"] = image["file_size"]
    reference["vendor_entries"] = dict(sorted(vendor.items()))
    reference["modules_load"] = len(module_list(entries, "modules.load"))
    reference["modules_load_recovery"] = len(module_list(entries, "modules.load.recovery"))
    with open(out_path, "w") as handle:
        json.dump(reference, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(f"reference: {len(vendor)} vendor entries written to {out_path}")


def check(image_path, reference_path, flavor, report_path):
    with open(reference_path) as handle:
        reference = json.load(handle)
    image = read_image(image_path)
    fragments, entries = ramdisk_view(image)
    by_name = {}
    duplicates = []
    for entry in entries:
        if entry["name"] in by_name:
            duplicates.append(entry["name"])
        by_name[entry["name"]] = entry

    results = []

    def record(name, ok, detail):
        results.append({"check": name, "ok": bool(ok), "detail": detail})

    record("header_version", image["header_version"] == 4, image["header_version"])
    record("page_size", image["page_size"] == reference["page_size"], image["page_size"])
    record("image_size_within_partition", image["file_size"] <= reference["partition_size"],
           f"{image['file_size']} <= {reference['partition_size']}")
    for field in ("kernel_addr", "ramdisk_addr", "tags_addr", "dtb_addr", "vendor_cmdline", "board_name",
                  "dtb_size", "dtb_sha256", "bootconfig", "bootconfig_size"):
        record(field, image[field] == reference[field], {"built": image[field], "stock": reference[field]})
    record("avb_footer", image["avb_footer"], image["avb_footer"])
    record("single_platform_fragment_like_stock",
           [(f["type"], f["name"]) for f in fragments] == [(1, "")],
           fragments)
    record("no_duplicate_cpio_entries", not duplicates, duplicates[:20])

    stock_vendor = reference["vendor_entries"]
    built_vendor = {name: describe_entry(entry) for name, entry in by_name.items() if is_vendor_path(name)}
    missing = sorted(set(stock_vendor) - set(built_vendor))
    extra = sorted(set(built_vendor) - set(stock_vendor))
    changed = sorted(name for name in set(stock_vendor) & set(built_vendor) if stock_vendor[name] != built_vendor[name])
    record("stock_vendor_ramdisk_intact", not (missing or extra or changed),
           {"stock_entries": len(stock_vendor), "built_entries": len(built_vendor),
            "missing": missing[:20], "extra": extra[:20], "changed": changed[:20]})

    modules_load = len(module_list(entries, "modules.load"))
    modules_recovery = len(module_list(entries, "modules.load.recovery"))
    record("first_stage_module_lists",
           (modules_load, modules_recovery) == (reference["modules_load"], reference["modules_load_recovery"]),
           {"modules.load": modules_load, "modules.load.recovery": modules_recovery})

    markers = RECOVERY_MARKERS[flavor]
    absent = [marker for marker in markers
              if marker not in by_name and not any(name.startswith(marker + "/") for name in by_name)]
    recovery_entries = sum(1 for name in by_name if not is_vendor_path(name))
    record(f"{flavor}_recovery_ramdisk_present", not absent,
           {"missing_markers": absent, "recovery_entries": recovery_entries})

    summary = {
        "image": os.path.basename(image_path),
        "sha256": sha256(open(image_path, "rb").read()),
        "flavor": flavor,
        "file_size": image["file_size"],
        "vendor_ramdisk_total_size": image["vendor_ramdisk_total_size"],
        "fragments": fragments,
        "passed": all(item["ok"] for item in results),
        "checks": results,
    }
    for item in results:
        print(f"{'PASS' if item['ok'] else 'FAIL'}  {item['check']}: {json.dumps(item['detail'])}")
    print(f"RESULT {'PASS' if summary['passed'] else 'FAIL'} ({sum(i['ok'] for i in results)}/{len(results)})")
    if report_path:
        with open(report_path, "w") as handle:
            json.dump(summary, handle, indent=2)
            handle.write("\n")
    return 0 if summary["passed"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image")
    parser.add_argument("--reference", required=True)
    parser.add_argument("--emit-reference", action="store_true")
    parser.add_argument("--flavor", choices=sorted(RECOVERY_MARKERS), default="twrp")
    parser.add_argument("--report")
    args = parser.parse_args()
    if args.emit_reference:
        emit_reference(args.image, args.reference)
        return 0
    return check(args.image, args.reference, args.flavor, args.report)


if __name__ == "__main__":
    sys.exit(main())
