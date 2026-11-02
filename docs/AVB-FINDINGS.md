# Why recovery images never booted on mBlu 21 (2026-11-02)

## Summary

`vendor_boot` recovery images (OrangeFox r19 `f949c907…`, SHRP r19 `28b83130…`) are
statically valid: header v4, stock DTB, stock bootconfig, stock vendor cmdline, and
ramdisk content that matches the stock platform ramdisk. They still do not boot.
The blocker is not the ramdisk — it is the AVB blob carried inside the image.

## Evidence

Read from the live device (rooted, SukiSU Ultra 4.3.0) and from the stock dump in
`/mnt/c/Users/Public/mblu21-backup/dump`.

| Image | Embedded vbmeta public key (sha1) | Rollback index | Boots? |
|---|---|---|---|
| stock `vendor_boot_a` | `4fce36c73467e6d045abcd240d6c826511707e6e` (= chain key in stock `vbmeta_a`) | 1790812800 | yes |
| stock `init_boot_a` | `f1553ffc593bad11a048d0a4a215a5efbdc91307` | 0 | yes |
| SukiSU `init_boot` (patched ramdisk) | `f1553ffc593bad11a048d0a4a215a5efbdc91307` (kept) | 0 | **yes** |
| SHRP r19 `vendor_boot` | `2597c218aae470a130f61162feaae70afd97f011` (test key) | 0 | no |
| OrangeFox r19 `vendor_boot` | `2597c218aae470a130f61162feaae70afd97f011` (test key) | 0 | no |
| `vbmeta_a` rebuilt flags 3, unsigned | none (algorithm NONE) | 0 | no |
| `vbmeta_a` rebuilt flags 3, RSA4096 test key | test key | 0 | no |

Two independent differences appear in every image that failed, and neither appears in
any image that booted:

1. the embedded vbmeta is **not signed with the Meizu chain key**, and
2. its **rollback index is 0** while the stock chain entry for `vendor_boot` is
   `1790812800`.

So the earlier claim "init_boot is not AVB-verified" was wrong. The 1-byte probe that
"proved" it changed a byte in the AVB **footer** (`vendor_boot_probe.img` and
`boot_probe.img` differ from stock at offset `size-15`, inside `reserved[0..27]` of the
footer, which no verification path reads). Content inside the hashed region is verified:
`avbtool verify_image` rejects it, and the same tampered image written to the device did
not boot.

## What the bootloader actually does

Strings extracted from the stock `uboot_a.bin` (`e91bff5c…`) show two layers:

- `avb_slot_verify()` with `read_is_device_unlocked()` and the literal message
  `avb allow verification error in UNLOCK status while normal booting`, i.e. unlocked
  boot accepts AVB failures in normal boot.
- a SPRD-specific wrapper `secure_avb_verify_image()` / `vboot_verify_vbmeta()` that
  checks `check vbmeta sprd sign image header magic number error!`, plus an allowlist of
  partitions that must be secure images (`splloader0`, `mobilevisor`, `secvm`,
  `trustos`, `gnssmodem`, `wcnmodem`, modem images).

The observation that fits both layers: a vbmeta that is **absent** (the per-partition
images that keep their stock blob, and `vbmeta_a` restored to stock) is tolerated, while
a vbmeta that is **present but foreign** is rejected. Both replace-vbmeta attempts
published a foreign vbmeta, and both stopped at the logo.

## Status of each attempt (2026-11-02)

| Attempt | What was written | Result |
|---|---|---|
| stock boot + SHRP vendor_boot + `vbmeta` flags 3 (unsigned) | `vendor_boot_a`, `vbmeta_a`, `misc=boot-recovery` | stop at logo |
| same, with `vbmeta` flags 3 signed by an RSA-4096 test key | `vbmeta_a` | stop at logo |
| vendor_boot only (SHRP), `vbmeta` restored to stock | `vendor_boot_a` = test-key SHRP image | phone stopped enumerating USB (boot failure); restore pending |
| SHRP vendor_boot content with the **stock Meizu vbmeta blob** inside | `vendor_boot_a` | not yet completed against a healthy phone |

## Next experiments, in order

1. **Stock blob swap (ready).** `~/mblu21-flash/recovery2/vb-shrp-stockavb.img` and
   `vb-ofox-stockavb.img` keep the recovery ramdisk and carry the stock
   `vendor_boot` AVB blob verbatim (`06daaf6e…`, key `4fce36c7…`, rollback
   `1790812800`). This is the one shape never tried: a partition whose vbmeta is
   Meizu-signed but whose content is not.
2. **1-byte content probe.** `~/mblu21-flash/probe2/P1_content_1byte.img` changes one
   byte of the stock ramdisk and keeps the stock AVB blob. Booting it proves whether the
   bootloader hashes `vendor_boot` content or only validates the blob.
3. `init_boot` recovery variant needs a ramdisk under 8 MB (stock partition minus the
   2240-byte AVB blob); the current SHRP/OrangeFox ramdisks are 43 MB and 50 MB, so they
   only fit in `vendor_boot`.
4. Re-dump `vbmeta_a` from a running phone and inspect the SPRD signature block that
   `uboot` looks for; only a Meizu-signed vbmeta can be published.

## Restore path

`vendor_boot_a` + `misc` from the stock dump, written in Unisoc download mode
(`Volume Up` + USB) with `spd_dump`, is sufficient to return the phone to stock; no other
partition was touched by this experiment. `~/re/lineage-24.0-logs/step6-restore-stock.sh`
does exactly that and logs to `step6-restore-stock.log`.
