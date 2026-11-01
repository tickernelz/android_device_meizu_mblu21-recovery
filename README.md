# TWRP and OrangeFox for Meizu mBlu 21 (M416H)

Recovery device tree for the Meizu mBlu 21, model M416H. One tree builds both TWRP and OrangeFox; GitHub Actions in this repository builds them and publishes `vendor_boot.img` as pre-releases.

| | |
|---|---|
| SoC | Unisoc T606 (UMS9230), board `ums9230_6h10` |
| Storage | UFS, A/B, virtual A/B, dynamic partitions |
| Kernel | stock GKI `5.15.149-android13-8` in `boot` (not touched) |
| Recovery location | `vendor_boot` (there is no `recovery` partition) |

## Status

**UNTESTED.** Nobody has booted these images on a phone. Every release is a pre-release with `UNTESTED` in its name. The only proof so far is the static check below, which runs in CI on every build.

## How recovery lives on this phone

The phone has no `recovery` partition. The stock recovery sits inside the `vendor_boot` ramdisk, header v4, as a single ramdisk fragment that also carries the first-stage ramdisk (`first_stage_ramdisk/`) and the first-stage kernel modules (`lib/modules/`). The bootloader loads that same `vendor_boot` on every boot, normal or recovery. Init decides which one to run: a normal boot switches root into `first_stage_ramdisk/`, a recovery boot stays at the ramdisk root where the recovery lives.

This tree reproduces that layout:

- `BOARD_MOVE_RECOVERY_RESOURCES_TO_VENDOR_BOOT := true` without `BOARD_INCLUDE_RECOVERY_RAMDISK_IN_VENDOR_BOOT`, so the build merges the recovery into the one vendor ramdisk fragment instead of adding a separate `recovery` fragment the Unisoc bootloader has never been shown to load.
- `prebuilt/vendor_ramdisk/` holds the stock `first_stage_ramdisk/` and `lib/modules/` taken from the dumped `vendor_boot_a`; the `mblu21_stock_vendor_ramdisk` module copies them into the vendor ramdisk unchanged.
- `prebuilt/dtb/stock.dtb`, the vendor command line, bootconfig and load addresses are the stock values.
- The image carries an AVB hash footer signed with the public AOSP test key, rollback index location 18 like stock.

Because normal boot uses the same image, anything that differs from stock outside the recovery part would affect normal boot. CI therefore checks every build against `prebuilt/stock_vendor_boot.json`, recorded from the stock dump with `tools/vendor_boot_check.py --emit-reference`:

| Check | Required |
|---|---|
| header version, page size | 4, 4096 |
| image size | at most 104,857,600 bytes (`vendor_boot` partition) |
| vendor command line | `console=ttyS1,115200n8 bootconfig bootconfig` |
| bootconfig | `androidboot.hardware=ums9230_6h10` (34 bytes) |
| DTB | 129,485 bytes, SHA-256 equal to stock |
| kernel, ramdisk, tags, DTB addresses | equal to stock |
| ramdisk table | one fragment, type 1, no name, like stock |
| `first_stage_ramdisk/`, `lib/modules/` | all 180 stock entries present, same mode, owner and SHA-256, nothing added |
| module lists | `modules.load` 72 and `modules.load.recovery` 139 entries |
| recovery | `system/bin/recovery` and `twres/` present (OrangeFox also `FFiles/`) |
| TEE stack | the 6 Trusty/keymint/gatekeeper programs, their rc file, VINTF fragments, the gatekeeper and rpmbmac trusted apps, and `keystore2`, `servicemanager`, `hwservicemanager` are in the ramdisk |
| TEE libraries | every `DT_NEEDED` of those programs resolves inside the ramdisk through `/vendor/lib64`, `/vendor/lib64/hw`, `/system/lib64`, and every non-weak undefined symbol is defined by the loaded set |
| TEE start order | keymint and gatekeeper start only after `tee_rpc` and `tsupplicant` are running |
| fstab | `/data` and `/metadata` in the recovery fstab equal the ROM fstab (`prebuilt/fstab.rom.ums9230_6h10`): file system, mount options, `fileencryption=`, `keydirectory=` |
| version props | `ro.build.version.release` 99.87.36, `ro.build.version.security_patch` and `ro.vendor.build.security_patch` 2099-12-31 |

The release notes of every build contain the full check output.

## Decryption

LineageOS 24 and the stock ROM encrypt `/data` with FBE v2 (`aes-256-xts:aes-256-cts:v2+inlinecrypt_optimized`) plus metadata encryption (`keydirectory=/metadata/vold/metadata_encryption`). The keys are wrapped by KeyMint in Unisoc Trusty and the lock screen PIN is checked by the Trusty gatekeeper. The recovery therefore carries the stock TEE stack from the phone's `vendor` and `odm` partitions:

| Piece | Stock source | In the recovery |
|---|---|---|
| `tee_rpc`, `tsupplicant` (loads trusted apps), `vendor.sprd.hardware.trusty-service` | `vendor/bin` | `/system/bin` |
| `sprdstorageproxyd` (Trusty secure storage: RPMB, prodnv, `/data/vendor`) | `vendor/bin` | `/system/bin` |
| KeyMint 2.0 (`android.hardware.security.keymint@2.0-unisoc.service.trusty`) | `vendor/bin/hw` | `/system/bin` |
| Gatekeeper 1.0 (`android.hardware.gatekeeper@1.0-service.trusty`) | `vendor/bin/hw` | `/system/bin` |
| Gatekeeper and RPMB MAC trusted apps | `odm/firmware/gatekeeper.elf`, `vendor/firmware/rpmbmac.elf` | `/vendor/firmware`, `/vendor/odm/firmware` |
| 12 vendor libraries, 8 VNDK-33 libraries the stack links against | `vendor/lib64`, `com.android.vndk.v33` | `/vendor/lib64` |
| VINTF fragments for KeyMint, Gatekeeper, Trusty | `vendor/etc/vintf/manifest` | `/vendor/etc/vintf/manifest` |

`init.recovery.ums9230_6h10.rc` starts them as the ROM does, in this order: when TWRP marks `/data` encrypted it mounts `prodnv` on `/mnt/vendor`, starts the RPMB and prodnv storage proxies, `tee_rpc`, `tsupplicant` and the Trusty service; KeyMint and Gatekeeper start once `tee_rpc` and `tsupplicant` are running; the `/data/vendor` storage proxies start only after the device-encrypted part of `/data` is readable, and stop once all users are decrypted so `/data` can be unmounted.

The recovery reports Android `99.87.36`, security patch `2099-12-31`. KeyMint rejects keys made under a newer patch level than the running system reports; a higher patch level instead makes KeyMint ask for a key upgrade. TWRP and OrangeFox write upgraded key blobs only to `/tmp` (`KeyStorage.cpp` in their vold) and run keystore2 on a copy of its database in `/tmp`, so nothing on the phone is rewritten.

Format compatibility with Android 17, checked against the LineageOS 24 sources (`frameworks/base` at `0a8b4cbd4`, `system/vold`, `system/security` at `123cc4a`):

- Lock screen: the phone has no Weaver HAL, so the PIN goes through the Gatekeeper path. In Android 17 that path is unchanged from Android 14: same synthetic password blob versions (V1-V3), same `PasswordData` layout, scrypt parameters, `secdiscardable` transform, protector key alias and `fbe-key` derivation. Only the Weaver path changed, which this phone does not use.
- vold key storage: same file names and versions, same keystore-wrapped key format; metadata encryption on a single `userdata` device uses the same key directory layout.
- keystore2 database: Android 17 writes schema version 2. OrangeFox 16 reads version 2 natively. TWRP 14.1 knows version 1, but its upgrade loop only runs upward, keeps the stored version and reads the same tables; it works on a copy in `/tmp`.

What only the phone can prove: that the Unisoc TEE accepts these services in recovery, that `tsupplicant` loads the gatekeeper app from the recovery paths, and that a PIN set on LineageOS 24 unlocks `/data`. This is test item one of the first session with the phone.

## Things to know before flashing

- **Only one recovery fits.** Lineage Recovery, the stock Meizu recovery, TWRP and OrangeFox all live in `vendor_boot` and replace each other. Flashing one removes the other.
- **ROM updates overwrite it.** Anything that writes `vendor_boot` (a LineageOS ZIP or OTA, a stock firmware flash) replaces TWRP or OrangeFox with the recovery bundled in that image. A/B updates write the inactive slot, so after such an update the next boot runs the recovery from the new slot. Flash TWRP or OrangeFox again afterwards if you want to keep it.
- **`/data` decryption is built in but unproven.** See [Decryption](#decryption). Until it is tested on the phone, expect that it may fail; ADB sideload, microSD and USB OTG do not depend on `/data`.
- **Unlocked bootloader required.** The image is signed with the AOSP test key. The bootloader must be unlocked and `vbmeta` must not enforce verification, exactly as for the LineageOS builds of this phone.
- **Unverified on hardware:** touch (the `focaltech_spi_v4_1` and `spi_ilitek` modules are loaded from `vendor_dlkm`, with copies in the ramdisk as a fallback), screen height (1600 assumed; the theme scales), brightness range, the USB OTG block device (`/dev/block/sdg1` assumed), MTP and slot switching through the AOSP boot control HAL.

## Flashing

Keep the full backup of the phone (`vendor_boot_a.bin` from the dump) before you start.

1. Download `...-vendor_boot.img` and its `.sha256` from a release and check it:
   ```sh
   sha256sum -c mblu21-*-vendor_boot.img.sha256
   ```
2. Reboot to the bootloader (`adb reboot bootloader`) and flash the active slot:
   ```sh
   fastboot getvar current-slot
   fastboot flash vendor_boot_a mblu21-twrp-...-vendor_boot.img
   ```
   Use `vendor_boot_b` when the current slot is `b`. Flash both slots to keep the recovery after an A/B update. `fastboot boot` does not work for `vendor_boot` images.
3. Boot into recovery with `fastboot reboot recovery` or `adb reboot recovery`.

## Going back

- **Stock recovery:** flash the stock image from the backup: `fastboot flash vendor_boot_a vendor_boot_a.bin` (and `_b` if you flashed it).
- **Lineage Recovery:** flash `vendor_boot.img` from the LineageOS build of this phone to the same slot.
- **From TWRP/OrangeFox itself:** Install, Install Image, pick the image, target `Vendor Boot (recovery)`.

If the phone no longer boots at all after flashing, flash the stock `vendor_boot_a.bin` from the bootloader; the bootloader itself is not touched by this image.

## Building

CI does the builds: `.github/workflows/build.yml` runs a matrix of TWRP (`twrp-14.1`) and OrangeFox (`fox_16.0`) on every push to `main` and on manual dispatch, then publishes a pre-release per flavour with the image, its SHA-256 and the check report.

Manifest choice: the newest branch of each project, because decryption has to read data written by Android 17.

- TWRP: `twrp-14.1` (Android 14). TeamWin has no newer recovery branch (`android_bootable_recovery` ends at `android-14.1`).
- OrangeFox: `fox_16.0` (Android 16, `android-16.0.0_r1`), the newest OrangeFox manifest and the only one whose keystore2 already uses the Android 17 database version. It builds with `lunch twrp_mblu21-bp2a-eng`.

Local build:

```sh
repo init --depth=1 -u https://github.com/minimal-manifest-twrp/platform_manifest_twrp_aosp.git -b twrp-14.1
repo sync -c --no-tags --no-clone-bundle
git clone https://github.com/tickernelz/android_device_meizu_mblu21-twrp device/meizu/mblu21
export ALLOW_MISSING_DEPENDENCIES=true
source build/envsetup.sh
lunch twrp_mblu21-ap2a-eng
mka vendorbootimage
python3 device/meizu/mblu21/tools/vendor_boot_check.py out/target/product/mblu21/vendor_boot.img \
  --reference device/meizu/mblu21/prebuilt/stock_vendor_boot.json --flavor twrp \
  --rom-fstab device/meizu/mblu21/prebuilt/fstab.rom.ums9230_6h10
```

For OrangeFox, sync with `orangefox_sync.sh --branch 16.0`, run `source device/meizu/mblu21/orangefox_vars.sh` before `build/envsetup.sh`, then `lunch twrp_mblu21-bp2a-eng` and `mka vendorbootimage`.

## Sources

- Stock files in `prebuilt/` and `recovery/root/` (`ueventd.ums9230_6h10.rc`, touch modules) come from the M416H firmware. They belong to Meizu and Unisoc and are included only so the device keeps booting with this image.
- LineageOS device tree: [tickernelz/android_device_meizu_mblu21](https://github.com/tickernelz/android_device_meizu_mblu21).

Licensed under Apache-2.0, except the stock firmware files listed above.
