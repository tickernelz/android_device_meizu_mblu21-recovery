#!/usr/bin/env python3
"""Compare a vendor_boot v4 image against the stock reference recorded from the M416H dump, except the first-stage fstab, which drops avb flags."""

import argparse
import hashlib
import json
import os
import re
import struct
import zipfile
import subprocess
import sys

from elfinfo import parse as parse_elf

VENDOR_PREFIXES = ("first_stage_ramdisk", "lib/modules")
INTENDED_VENDOR_CHANGES = {"first_stage_ramdisk/fstab.ums9230_6h10"}
HEADER_FORMAT = "<8sIIIII2048sI16sIIQIIII"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)
TABLE_ENTRY_FORMAT = "<III32s64s"
TABLE_ENTRY_SIZE = struct.calcsize(TABLE_ENTRY_FORMAT)
RECOVERY_MARKERS = {
    "orangefox": ("system/bin/recovery", "twres", "FFiles"),
    "shrp": ("system/bin/recovery", "twres", "twres/version"),
}
TEE_EXECUTABLES = (
    "system/bin/android.hardware.security.keymint@2.0-unisoc.service.trusty",
    "system/bin/android.hardware.gatekeeper@1.0-service.trusty",
    "system/bin/vendor.sprd.hardware.trusty-service",
    "system/bin/tee_rpc",
    "system/bin/tsupplicant",
    "system/bin/sprdstorageproxyd",
    "vendor/lib64/hw/vendor.sprd.hardware.trusty-impl.so",
)
TEE_DATA = (
    "init.recovery.ums9230_6h10.rc",
    "system/bin/mblu21-data-vendor-wait.sh",
    "vendor/lib64/vndk33-libbase/libbase.so",
    "vendor/firmware/gatekeeper.elf",
    "vendor/odm/firmware/gatekeeper.elf",
    "vendor/firmware/rpmbmac.elf",
    "vendor/etc/vintf/manifest/android.hardware.security.keymint@2.0-unisoc.service.trusty.xml",
    "vendor/etc/vintf/manifest/android.hardware.gatekeeper@1.0-service.trusty.xml",
    "vendor/etc/vintf/manifest/trusty-default.xml",
    "vendor/etc/vintf/manifest.xml",
    "system/etc/vintf/manifest.xml",
    "system/etc/task_profiles.json",
)
RECOVERY_CRYPTO_BINARIES = (
    "system/bin/keystore2",
    "system/bin/servicemanager",
    "system/bin/hwservicemanager",
)
STOCK_SERVICE_EXECUTABLES = TEE_EXECUTABLES + ("system/bin/vendor.sprd.hardware.vibrator-service",)
LIBRARY_SEARCH_PATH = ("vendor/lib64", "vendor/lib64/hw", "system/lib64")
SYSTEM_SEARCH_PATH = ("system/lib64",)
TEE_SERVICE_NAMES = (
    "vendor.rpmbproxy", "vendor.prodproxy", "vendor.nsproxy", "vendor.teensproxy", "vendor.tee_rpc", "vendor.tsupplicant",
    "vendor.sprd.hardware.trusty-service", "vendor.keymint-unisoc-2.0", "vendor.gatekeeper-1-0", "mblu21.data-vendor-wait",
)
KEYMINT_START_REQUIRES = ("init.svc.vendor.tee_rpc=running", "init.svc.vendor.tsupplicant=running")
SPOOFED_PROPS = {
    "ro.build.version.security_patch": "2099-12-31",
    "ro.vendor.build.security_patch": "2099-12-31",
    "ro.build.version.release": "99.87.36",
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
    if kind == 0o120000:
        return {"type": "symlink", "link": entry["content"].decode()}
    record = {"mode": oct(entry["mode"]), "uid": entry["uid"], "gid": entry["gid"]}
    if kind == 0o100000:
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


def resolve(by_name, path, depth=0):
    entry = by_name.get(path)
    if entry is None or depth > 8:
        return None
    if entry["mode"] & 0o170000 == 0o120000:
        target = entry["content"].decode()
        target = target.lstrip("/") if target.startswith("/") else os.path.normpath(os.path.join(os.path.dirname(path), target))
        return resolve(by_name, target, depth + 1)
    return entry


def load_set(by_name, root, search_path=LIBRARY_SEARCH_PATH):
    elves = {}
    missing = []
    queue = [root]
    while queue:
        path = queue.pop()
        if path in elves:
            continue
        info = parse_elf(resolve(by_name, path)["content"])
        elves[path] = info
        for lib in info["needed"]:
            for directory in search_path:
                candidate = f"{directory}/{lib}"
                if resolve(by_name, candidate) is not None:
                    queue.append(candidate)
                    break
            else:
                missing.append(f"{os.path.basename(path)} -> {lib}")
    return elves, missing


def parse_fstab(text):
    entries = {}
    for line in text.splitlines():
        fields = line.split()
        if len(fields) < 5 or fields[0].startswith("#"):
            continue
        entries.setdefault(fields[1], []).append({
            "fs": fields[2], "options": sorted(fields[3].split(",")), "flags": sorted(fields[4].split(","))})
    return entries


def parse_props(by_name):
    props = {}
    for name in sorted(by_name):
        if name in ("prop.default", "default.prop") or name.endswith("/build.prop"):
            if is_vendor_path(name):
                continue
            entry = resolve(by_name, name)
            if entry is None:
                continue
            for line in entry["content"].decode(errors="replace").splitlines():
                if "=" in line and not line.startswith("#"):
                    key, value = line.split("=", 1)
                    props.setdefault(key.strip(), value.strip())
    return props


def rc_services_and_triggers(text):
    services = {}
    library_paths = {}
    triggers = []
    current = None
    service = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("service "):
            parts = line.split()
            services[parts[1]] = parts[2]
            service = parts[2].lstrip("/")
            current = None
        elif service and line.startswith("setenv LD_LIBRARY_PATH "):
            library_paths[service] = tuple(part.lstrip("/") for part in line.split()[2].split(":"))
        elif line.startswith("on "):
            current = {"trigger": line[3:], "commands": []}
            triggers.append(current)
            service = None
        elif current is not None and line:
            current["commands"].append(line)
    return services, triggers, library_paths


def crypto_checks(by_name, rom_fstab_path, record):
    required = STOCK_SERVICE_EXECUTABLES + TEE_DATA + RECOVERY_CRYPTO_BINARIES
    absent = [path for path in required if resolve(by_name, path) is None]
    record("tee_stack_files_present", not absent, {"required": len(required), "missing": absent})
    if absent:
        return

    rc_text = resolve(by_name, "init.recovery.ums9230_6h10.rc")["content"].decode()
    services, triggers, library_paths = rc_services_and_triggers(rc_text)

    unresolved = []
    undefined = []
    loaded = set()
    for root in STOCK_SERVICE_EXECUTABLES:
        elves, missing = load_set(by_name, root, library_paths.get(root, LIBRARY_SEARCH_PATH))
        unresolved.extend(missing)
        loaded.update(elves)
        available = set().union(*(info["defined"] for info in elves.values()))
        for path, info in elves.items():
            for symbol in sorted(info["undefined"] - available):
                undefined.append(f"{os.path.basename(root)}: {os.path.basename(path)} needs {symbol}")
    record("stock_service_libraries_resolved", not unresolved,
           {"objects_loaded": len(loaded), "service_library_paths": {os.path.basename(k): ":".join(v) for k, v in sorted(library_paths.items())},
            "unresolved": sorted(set(unresolved))[:40]})
    record("stock_service_symbols_resolved", not undefined,
           {"unresolved_symbols": len(undefined), "sample": undefined[:40]})

    system_unresolved = []
    for root in RECOVERY_CRYPTO_BINARIES:
        elves, missing = load_set(by_name, root, SYSTEM_SEARCH_PATH)
        system_unresolved.extend(missing)
        available = set().union(*(info["defined"] for info in elves.values()))
        for path, info in elves.items():
            system_unresolved.extend(f"{os.path.basename(root)}: {os.path.basename(path)} needs {symbol}"
                                     for symbol in sorted(info["undefined"] - available))
    record("recovery_keystore_and_service_managers_link", not system_unresolved,
           {"binaries": RECOVERY_CRYPTO_BINARIES, "unresolved": system_unresolved[:40]})

    stock_roots = set(STOCK_SERVICE_EXECUTABLES)
    system_elves = sorted(name for name, entry in by_name.items()
                          if name.startswith(("system/bin/", "system/lib64/")) and name not in stock_roots
                          and not name.startswith("system/lib64/hw/")
                          and entry["mode"] & 0o170000 == 0o100000 and entry["content"][:4] == b"\x7fELF")
    unlinked = []
    for root in system_elves:
        try:
            unlinked.extend(load_set(by_name, root, SYSTEM_SEARCH_PATH)[1])
        except ValueError:
            continue
    record("system_binaries_link", not unlinked,
           {"objects": len(system_elves), "unresolved": sorted(set(unlinked))[:40]})

    tee_services = {name: services.get(name) for name in TEE_SERVICE_NAMES}
    bad_paths = {name: path for name, path in tee_services.items()
                 if path is None or resolve(by_name, path.lstrip("/")) is None}
    keymint_triggers = [t["trigger"] for t in triggers if "start vendor.keymint-unisoc-2.0" in t["commands"]]
    ordered = bool(keymint_triggers) and all(all(req in trig for req in KEYMINT_START_REQUIRES) for trig in keymint_triggers)
    record("tee_services_defined_and_ordered", not bad_paths and ordered,
           {"tee_services": sorted(tee_services), "bad_paths": bad_paths, "keymint_start_triggers": keymint_triggers})

    rom = parse_fstab(open(rom_fstab_path).read())
    fstab_entry = resolve(by_name, "system/etc/recovery.fstab")
    recovery = parse_fstab(fstab_entry["content"].decode()) if fstab_entry else {}
    mismatches = {}
    for mount in ("/data", "/metadata"):
        built = recovery.get(mount, [])
        if not built:
            mismatches[mount] = "missing in recovery.fstab"
            continue
        for entry in built:
            if entry not in rom.get(mount, []):
                mismatches[mount] = {"recovery": entry, "rom": rom.get(mount, [])}
    data = recovery.get("/data", [{}])[0]
    record("recovery_fstab_encryption_matches_rom", not mismatches,
           {"fileencryption": [f for f in data.get("flags", []) if f.startswith(("fileencryption=", "keydirectory=", "metadata_encryption="))],
            "mismatches": mismatches})

    props = parse_props(by_name)
    seen = {key: props.get(key) for key in SPOOFED_PROPS}
    record("keymint_version_props_spoofed", seen == SPOOFED_PROPS, seen)


FEATURE_PHONE_TESTS = {
    "decrypt_data": "Boot recovery on LineageOS 24 with a PIN set, enter the PIN, /data/media/0 file names are readable",
    "mtp": "Connect to a PC, the internal storage appears as an MTP device and a file copies both ways",
    "adb_sideload": "adb devices lists the phone in recovery; adb sideload of a ZIP completes",
    "fastbootd": "Reboot to fastbootd from recovery; fastboot getvar is-userspace returns yes",
    "otg_usb_storage": "A FAT32 USB stick on an OTG adapter mounts as USB OTG",
    "flash_zip_image": "Flash a ZIP and flash vendor_boot.img through Install Image",
    "backup_restore": "Back up boot, init_boot, vendor_boot, dtbo, super and metadata, restore boot, phone still boots",
    "touch": "Touch responds over the whole screen",
    "brightness": "The brightness slider changes the backlight",
    "display": "The UI fills the 720x1600 panel with nothing cut off",
    "battery": "The battery percentage matches Android and the charging mark shows on a charger",
    "vibrator": "Buttons vibrate",
    "terminal": "The terminal opens and runs ls /data",
    "orangefox_ota_survival": "After a LineageOS ZIP install, OrangeFox reflashes itself and is still the recovery after reboot",
    "orangefox_themes": "Changing accent and theme in settings persists across reboot",
    "orangefox_installer_zip": "Install the OrangeFox ZIP from OrangeFox itself; both vendor_boot slots then hold the released image and the phone boots to OrangeFox",
    "shrp_device_flags": "About shows device mblu21, A/B, maintainer tickernelz",
    "shrp_express_settings": "Change the theme and set a recovery lock; both survive a reboot, /data/unencrypted/etc/shrp holds them, and boot_a/boot_b SHA-256 are unchanged",
}


def contains(by_name, paths, needle):
    data = needle.encode()
    for path in paths:
        entry = resolve(by_name, path)
        if entry is not None and data in entry["content"]:
            return True
    return False


def parse_twrp_flags(by_name):
    entry = resolve(by_name, "system/etc/twrp.flags")
    flags = {}
    if entry is None:
        return flags
    for line in entry["content"].decode().splitlines():
        fields = line.split()
        if len(fields) >= 3 and not line.startswith("#"):
            flags[fields[0]] = line
    return flags


def rc_text(by_name):
    texts = []
    for name in by_name:
        if name.endswith(".rc") and not is_vendor_path(name):
            entry = resolve(by_name, name)
            if entry is not None:
                texts.append(entry["content"].decode(errors="replace"))
    return "\n".join(texts)


def zip_member(zip_path, name):
    with zipfile.ZipFile(zip_path) as archive:
        return archive.read(name) if name in archive.namelist() else None


def feature_checks(by_name, flavor, zip_path, results, record, image_sha256=None):
    recovery = ("system/bin/recovery",)
    libs = tuple(name for name in by_name if name.startswith("system/lib64/"))
    flags = parse_twrp_flags(by_name)
    rc = rc_text(by_name)
    recovery_modules = set(module_list(list(by_name.values()), "modules.load.recovery"))

    def has(path):
        return resolve(by_name, path) is not None

    device_rc = resolve(by_name, "init.recovery.ums9230_6h10.rc")
    device_services = rc_services_and_triggers(device_rc["content"].decode())[0] if device_rc else {}
    vibrator_path = device_services.get("vendor.vibrator", "")
    vibrator_service_ok = bool(vibrator_path) and has(vibrator_path.lstrip("/"))

    def flag_has(mount, token):
        return token in flags.get(mount, "")

    crypto_prefixes = ("tee_", "stock_service_", "recovery_keystore", "recovery_fstab", "keymint_version")
    crypto = {item["check"]: item["ok"] for item in results if item["check"].startswith(crypto_prefixes)}
    features = {
        "decrypt_data": (all(crypto.values()) and bool(crypto), {"from_checks": crypto}),
        "mtp": (contains(by_name, recovery + libs, "/dev/usb-ffs/mtp/ep0") and "functionfs mtp" in rc and "ffs.mtp" in rc,
                {"ffs_endpoint_in_binary": contains(by_name, recovery + libs, "/dev/usb-ffs/mtp/ep0"), "rc_ffs_mtp": "ffs.mtp" in rc}),
        "adb_sideload": (has("system/bin/adbd") and contains(by_name, recovery, "sideload"),
                         {"adbd": has("system/bin/adbd")}),
        "fastbootd": (has("system/bin/fastbootd") and "service fastbootd" in rc, {"fastbootd": has("system/bin/fastbootd")}),
        "otg_usb_storage": ("/usb_otg" in flags and {"musb_hdrc.ko", "musb_sprd.ko"} <= recovery_modules,
                            {"usb_otg_flag": "/usb_otg" in flags, "musb_modules": sorted({"musb_hdrc.ko", "musb_sprd.ko"} & recovery_modules)}),
        "flash_zip_image": (all(flag_has(m, "flashimg=1") for m in ("/boot", "/init_boot", "/vendor_boot", "/dtbo")) and contains(by_name, recovery, "update-binary"),
                            {m: flag_has(m, "flashimg=1") for m in ("/boot", "/init_boot", "/vendor_boot", "/dtbo")}),
        "backup_restore": (all(flag_has(m, "backup=1") for m in ("/boot", "/init_boot", "/vendor_boot", "/dtbo", "/super", "/metadata")),
                           {m: flag_has(m, "backup=1") for m in ("/boot", "/init_boot", "/vendor_boot", "/dtbo", "/super", "/metadata")}),
        "touch": (has("vendor/lib/modules/1.1/focaltech_spi_v4_1.ko") and has("vendor/lib/modules/1.1/spi_ilitek.ko") and contains(by_name, recovery, "focaltech_spi_v4_1.ko"),
                  {"modules_in_ramdisk": has("vendor/lib/modules/1.1/spi_ilitek.ko"), "load_list_in_binary": contains(by_name, recovery, "spi_ilitek.ko")}),
        "brightness": (contains(by_name, recovery + libs, "/sys/class/backlight/sprd_backlight/brightness"), {}),
        "display": (has("twres/ui.xml"), {}),
        "battery": (contains(by_name, recovery, "/sys/class/power_supply/battery/capacity") and {"sc27xx_fuel_gauge.ko", "sprd-charger-manager.ko"} <= recovery_modules,
                    {"sysfs_reader_in_binary": contains(by_name, recovery, "/sys/class/power_supply/battery/capacity")}),
        "vibrator": (has("system/bin/vendor.sprd.hardware.vibrator-service") and has("vendor/etc/vintf/manifest/vibrator.xml")
                     and vibrator_service_ok and contains(by_name, recovery + libs, "IVibrator/default")
                     and "sc27xx-vibra.ko" in recovery_modules,
                     {"rc_service_path_resolves": vibrator_service_ok, "aidl_instance_in_binary": contains(by_name, recovery + libs, "IVibrator/default")}),
        "terminal": (has("system/bin/sh") and (has("sbin/bash") or has("system/bin/bash")), {"bash": has("sbin/bash") or has("system/bin/bash")}),
    }
    if flavor == "orangefox":
        binary = zip_member(zip_path, "META-INF/com/google/android/update-binary") if zip_path else None
        features["orangefox_ota_survival"] = (
            contains(by_name, recovery, "orangefox.vendor_boot.recovery") and binary is not None and b'FOX_VENDOR_BOOT_RECOVERY="1"' in binary,
            {"vendor_boot_mode_in_binary": contains(by_name, recovery, "orangefox.vendor_boot.recovery"), "installer_zip_vendor_boot": binary is not None and b'FOX_VENDOR_BOOT_RECOVERY="1"' in binary})
        features["orangefox_themes"] = (has("twres/themes/accent.xml") and has("twres/themes/style.xml"), {})
        installs_image = False
        detail = {"zip_given": bool(zip_path)}
        if zip_path:
            embedded = zip_member(zip_path, "recovery.img")
            with zipfile.ZipFile(zip_path) as archive:
                cpio = [n for n in archive.namelist() if n.endswith(".cpio")]
            whole_image = binary is not None and re.search(rb'^FOX_INSTALLER_VENDOR_BOOT_RAMDISK_INSTALL="?0"?$', binary, re.M) is not None
            same_image = embedded is not None and sha256(embedded) == image_sha256
            installs_image = whole_image and same_image
            detail.update({"whole_image_install": whole_image, "recovery_img_sha256_matches_image": same_image,
                           "ramdisk_cpio_in_zip": cpio})
        features["orangefox_installer_zip"] = (installs_image, detail)
    if flavor == "shrp":
        features["shrp_device_flags"] = (contains(by_name, recovery, "shrp_rec") and has("twres/version"), {})
        repack = {needle: contains(by_name, recovery + libs, needle) for needle in ("create_env", "by-name/boot_")}
        features["shrp_express_settings"] = (not any(repack.values()), {"legacy_repack_strings": repack})
    for name, (ok, detail) in features.items():
        record(f"feature_{name}", ok, dict(detail, phone_test=FEATURE_PHONE_TESTS[name]))

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


def check(image_path, reference_path, flavor, report_path, rom_fstab_path=None, zip_path=None):
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
    intended = [name for name in changed if name in INTENDED_VENDOR_CHANGES]
    changed = [name for name in changed if name not in INTENDED_VENDOR_CHANGES]
    first_stage_fstab = by_name.get("first_stage_ramdisk/fstab.ums9230_6h10", {}).get("content", b"").decode(errors="replace")
    record("first_stage_fstab_without_avb", first_stage_fstab and "avb=" not in first_stage_fstab and "avb_keys=" not in first_stage_fstab,
           [line for line in first_stage_fstab.splitlines() if "avb" in line][:4])
    ueventd = by_name.get("vendor/etc/ueventd.rc", {}).get("content", b"").decode(errors="replace")
    record("trusty_ipc_device_owned_by_system",
           any(line.split()[:4] == ["/dev/trusty-ipc-dev0", "0660", "system", "system"] for line in ueventd.splitlines()),
           "vendor/etc/ueventd.rc")
    framework_manifest = by_name.get("system/etc/vintf/manifest.xml", {}).get("content", b"").decode(errors="replace")
    record("hwservicemanager_declared_for_hidl_gatekeeper", "<name>android.hidl.manager</name>" in framework_manifest,
           "system/etc/vintf/manifest.xml")
    record("stock_vendor_ramdisk_intact", not (missing or extra or changed),
           {"stock_entries": len(stock_vendor), "built_entries": len(built_vendor),
            "missing": missing[:20], "extra": extra[:20], "changed": changed[:20], "intended_changes": intended})

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

    if rom_fstab_path:
        crypto_checks(by_name, rom_fstab_path, record)
        feature_checks(by_name, flavor, zip_path, results, record, sha256(open(image_path, "rb").read()))

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
    parser.add_argument("--flavor", choices=sorted(RECOVERY_MARKERS), required=True)
    parser.add_argument("--zip", help="flashable installer ZIP produced next to the image, checked when given")
    parser.add_argument("--report")
    parser.add_argument("--rom-fstab", help="ROM fstab whose /data and /metadata encryption options the recovery must match")
    args = parser.parse_args()
    if args.emit_reference:
        emit_reference(args.image, args.reference)
        return 0
    return check(args.image, args.reference, args.flavor, args.report, args.rom_fstab, args.zip)


if __name__ == "__main__":
    sys.exit(main())
