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

The release notes of every build contain the full check output.

## Things to know before flashing

- **Only one recovery fits.** Lineage Recovery, the stock Meizu recovery, TWRP and OrangeFox all live in `vendor_boot` and replace each other. Flashing one removes the other.
- **ROM updates overwrite it.** Anything that writes `vendor_boot` (a LineageOS ZIP or OTA, a stock firmware flash) replaces TWRP or OrangeFox with the recovery bundled in that image. A/B updates write the inactive slot, so after such an update the next boot runs the recovery from the new slot. Flash TWRP or OrangeFox again afterwards if you want to keep it.
- **No `/data` decryption.** This build does not include decryption. `/data` on the stock ROM and on LineageOS is encrypted with FBE, so its contents show up as unreadable names. ADB sideload, microSD and USB OTG do not depend on `/data`. Formatting data works and erases everything.
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

CI does the builds: `.github/workflows/build.yml` runs a matrix of TWRP (`twrp-14.1`) and OrangeFox (`fox_14.1`) on every push to `main` and on manual dispatch, then publishes a pre-release per flavour with the image, its SHA-256 and the check report.

Manifest choice: `twrp-14.1` is the newest TWRP minimal manifest (others: `twrp-11`, `twrp-12.1`, `twrp-14`). `fox_14.1` is built on the same TeamWin `android-14.1` base, so one tree serves both. OrangeFox also has `fox_16.0`, but it has no TWRP counterpart and would need a second variant of this tree; OrangeFox labels `fox_14.1` experimental.

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
  --reference device/meizu/mblu21/prebuilt/stock_vendor_boot.json --flavor twrp
```

For OrangeFox, sync with `orangefox_sync.sh --branch 14.1`, run `source device/meizu/mblu21/orangefox_vars.sh` before `build/envsetup.sh`, and build `mka adbd vendorbootimage`.

## Sources

- Stock files in `prebuilt/` and `recovery/root/` (`ueventd.ums9230_6h10.rc`, touch modules) come from the M416H firmware. They belong to Meizu and Unisoc and are included only so the device keeps booting with this image.
- LineageOS device tree: [tickernelz/android_device_meizu_mblu21](https://github.com/tickernelz/android_device_meizu_mblu21).

Licensed under Apache-2.0, except the stock firmware files listed above.
