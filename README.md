# OrangeFox and SHRP-Reborn for Meizu mBlu 21 (M416H)

Recovery device tree for the Meizu mBlu 21, model M416H. One tree builds OrangeFox and SHRP-Reborn (Skyhawk Recovery Project); GitHub Actions in this repository builds both and publishes `vendor_boot.img` as pre-releases. TWRP builds were dropped on 2026-11-02; their old releases are marked `SUPERSEDED`.

| | |
|---|---|
| SoC | Unisoc T606 (UMS9230), board `ums9230_6h10` |
| Storage | UFS, A/B, virtual A/B, dynamic partitions |
| Kernel | stock GKI `5.15.149-android13-8` in `boot` (not touched) |
| Recovery location | `vendor_boot` (there is no `recovery` partition) |

## Status

**OrangeFox boots and decrypts `/data` on the phone; SHRP-Reborn has not been tested.**

| Recovery | Tested on the phone |
|---|---|
| OrangeFox `fox_16.0`, built locally from branch `fix/fox-legacy-drm` at `b3dbb0c`, resealed with the stock Meizu AVB blob | 2026-11-03, one M416H on LineageOS 24.0: the UI shows and responds to touch, a PIN set on LineageOS unlocks `/data` (`Data successfully decrypted`, `/data/media/0` file names readable), `adb` sees the phone in recovery, and Android still boots normally with the same `vendor_boot`. |
| OrangeFox releases published so far, all built before `fix/fox-legacy-drm` | not tested; without that branch OrangeFox crash-loops on the boot logo |
| SHRP-Reborn `shrp-12.1`, every release | not tested |

Not tested on the phone yet, for either recovery: MTP, `adb sideload`, fastbootd, USB OTG, flashing a ZIP or image, backup and restore, battery, brightness, vibrator, OrangeFox OTA survival, and pressing Volume Down in recovery. Releases stay pre-releases; the ones not tested on the phone say `UNTESTED` in their name. CI runs the static check below on every build.

## How recovery lives on this phone

The phone has no `recovery` partition. The stock recovery sits inside the `vendor_boot` ramdisk, header v4, as a single ramdisk fragment that also carries the first-stage ramdisk (`first_stage_ramdisk/`) and the first-stage kernel modules (`lib/modules/`). The bootloader loads that same `vendor_boot` on every boot, normal or recovery. Init decides which one to run: a normal boot switches root into `first_stage_ramdisk/`, a recovery boot stays at the ramdisk root where the recovery lives.

This tree reproduces that layout:

- `BOARD_MOVE_RECOVERY_RESOURCES_TO_VENDOR_BOOT := true` without `BOARD_INCLUDE_RECOVERY_RAMDISK_IN_VENDOR_BOOT`, so the build merges the recovery into the one vendor ramdisk fragment instead of adding a separate `recovery` fragment the Unisoc bootloader has never been shown to load.
- `prebuilt/vendor_ramdisk/` holds the stock `first_stage_ramdisk/` and `lib/modules/` taken from the dumped `vendor_boot_a`; the `mblu21_stock_vendor_ramdisk` module copies them into the vendor ramdisk unchanged, except `first_stage_ramdisk/fstab.ums9230_6h10`, which drops the `avb=` and `avb_keys=` flags like the LineageOS `vendor_boot` does: the stock entries point at GSI keys that are not on the phone, and first-stage init then reboots to the bootloader.
- `prebuilt/dtb/stock.dtb`, the vendor command line, bootconfig and load addresses are the stock values.
- The image carries an AVB hash footer signed with the public AOSP test key, rollback index location 18 like stock.

Because normal boot uses the same image, anything that differs from stock outside the recovery part would affect normal boot. CI therefore checks every build against `prebuilt/stock_vendor_boot.json`, recorded from the stock dump with `tools/vendor_boot_check.py --emit-reference`; the one intended change, the first-stage fstab, is listed separately in the check output and guarded by `first_stage_fstab_without_avb`:

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
| recovery | `system/bin/recovery` and `twres/` present (OrangeFox also `FFiles/`, SHRP also `twres/version`) |
| TEE stack | the 6 Trusty/keymint/gatekeeper programs, the stock vibrator HAL, their rc file, VINTF fragments, the gatekeeper and rpmbmac trusted apps, and `keystore2`, `servicemanager`, `hwservicemanager` are in the ramdisk |
| stock service libraries | every `DT_NEEDED` of the stock TEE and vibrator programs resolves inside the ramdisk through the `LD_LIBRARY_PATH` its rc service sets, and every non-weak undefined symbol is defined by the loaded set |
| TEE start order | keymint and gatekeeper start only after `tee_rpc` and `tsupplicant` are running |
| fstab | `/data` and `/metadata` in the recovery fstab equal the ROM fstab (`prebuilt/fstab.rom.ums9230_6h10`): file system, mount options, `fileencryption=`, `keydirectory=` |
| version props | `ro.build.version.release` 99.87.36, `ro.build.version.security_patch` and `ro.vendor.build.security_patch` 2099-12-31 |
| features | the `feature_*` checks in [Features](#features) |

The release notes of every build contain the full check output.

## Features

Each feature has a static check in CI (`feature_*` in `validation.json`) and a test that only the phone can run. A failed phone test is a blocker, not a known issue.

| Feature | Static check in CI | Phone test (first session) |
|---|---|---|
| Decrypt `/data` | all TEE, stock service, keystore2, fstab and version-prop checks pass | Boot recovery on LineageOS 24 with a PIN set, enter the PIN, `/data/media/0` file names are readable |
| MTP | MTP FFS endpoint in the recovery, `ffs.mtp` gadget function in the rc | Internal storage shows on a PC over MTP; a file copies both ways |
| ADB and sideload | `adbd` present, sideload code in the recovery binary | `adb devices` sees the phone; `adb sideload` of a ZIP completes |
| fastbootd | `fastbootd` and its service present | Reboot to fastbootd; `fastboot getvar is-userspace` is `yes` |
| USB OTG storage | `/usb_otg` storage entry, `musb_hdrc` and `musb_sprd` in the recovery module list | A FAT32 stick on an OTG adapter mounts |
| Flash ZIP and image | `flashimg=1` for boot, init_boot, vendor_boot, dtbo; installer code in the binary | Flash a ZIP; flash `vendor_boot.img` through Install Image |
| Backup and restore | `backup=1` for boot, init_boot, vendor_boot, dtbo, super, metadata | Back up all six, restore boot, phone still boots |
| Touch | touch modules in the ramdisk and in the recovery's module load list | Touch works over the whole screen |
| Brightness | backlight path `/sys/class/backlight/sprd_backlight/brightness` in the binary | The slider changes the backlight |
| Display | theme present (`portrait_hdpi`, 720x1600, RGBX_8888) | UI fills the panel with nothing cut off |
| Battery | sysfs battery reader (`/sys/class/power_supply/battery/capacity`) in the binary; fuel gauge and charger-manager modules in the recovery module list | Percentage matches Android; charging mark shows on a charger |
| Vibrator | stock `vendor.sprd.hardware.vibrator-service` with its VINTF fragment and rc service; the recovery calls `IVibrator/default` | Buttons vibrate |
| Terminal | `sh` and `bash` present | Terminal opens and runs `ls /data` |
| OrangeFox: OTA survival | vendor_boot mode in the binary; installer ZIP has `FOX_VENDOR_BOOT_RECOVERY="1"` | After installing a LineageOS ZIP, OrangeFox reflashes itself and is still the recovery after reboot |
| OrangeFox: themes | accent and style theme files present | Theme and accent changes persist across reboot |
| SHRP: device flags | `shrp_rec` setting compiled in, `twres/version` present | About shows mblu21, A/B, maintainer |
| SHRP: theme and lock storage | Express mode compiled in: no `create_env*` repack scripts or `by-name/boot_` writes in the recovery | Change the theme and set a lock; both survive a reboot, `/data/unencrypted/etc/shrp` holds them, `boot_a`/`boot_b` SHA-256 unchanged |

OrangeFox on a virtual A/B device always builds as "vanilla": its MIUI block-OTA menu (`OF_SUPPORT_ALL_BLOCK_OTA_UPDATES`) is disabled by OrangeFox itself, so OTA survival here means the reflash after a ROM ZIP install.

The vibrator in this phone (`sc27xx-vibra`) is an input force-feedback device, which the recovery's built-in sysfs paths cannot drive, so the recovery uses the stock AIDL vibrator HAL (`TW_SUPPORT_INPUT_AIDL_HAPTICS`). The battery is read straight from sysfs (`TW_USE_LEGACY_BATTERY_SERVICES`) because the recovery has no health HAL for this phone.

## Decryption

LineageOS 24 and the stock ROM encrypt `/data` with FBE v2 (`aes-256-xts:aes-256-cts:v2+inlinecrypt_optimized`) plus metadata encryption (`keydirectory=/metadata/vold/metadata_encryption`). The keys are wrapped by KeyMint in Unisoc Trusty and the lock screen PIN is checked by the Trusty gatekeeper. The recovery therefore carries the stock TEE stack from the phone's `vendor` and `odm` partitions:

| Piece | Stock source | In the recovery |
|---|---|---|
| `tee_rpc`, `tsupplicant` (loads trusted apps), `vendor.sprd.hardware.trusty-service` | `vendor/bin` | `/system/bin` |
| `sprdstorageproxyd` (Trusty secure storage: RPMB, prodnv, `/data/vendor`) | `vendor/bin` | `/system/bin` |
| KeyMint 2.0 (`android.hardware.security.keymint@2.0-unisoc.service.trusty`) | `vendor/bin/hw` | `/system/bin` |
| Gatekeeper 1.0 (`android.hardware.gatekeeper@1.0-service.trusty`) | `vendor/bin/hw` | `/system/bin` |
| Gatekeeper and RPMB MAC trusted apps | `odm/firmware/gatekeeper.elf`, `vendor/firmware/rpmbmac.elf` | `/vendor/firmware`, `/vendor/odm/firmware` |
| 12 vendor libraries, 8 VNDK-33 libraries the stack links against that the recovery does not ship | `vendor/lib64`, `com.android.vndk.v33` | `/vendor/lib64` |
| VNDK-33 `libbase` for the storage proxies only (`sprdstorageproxyd` needs `android::base::Trim(std::string const&)`, which the Android 16 `libbase` no longer exports) | `com.android.vndk.v33` | `/vendor/lib64/vndk33-libbase`, first in those services' `LD_LIBRARY_PATH` |
| VINTF fragments for KeyMint, Gatekeeper, Trusty | `vendor/etc/vintf/manifest` | `/vendor/etc/vintf/manifest` |
| Empty base device manifest, and a framework manifest declaring `android.hidl.manager` | — | `/vendor/etc/vintf/manifest.xml`, `/system/etc/vintf/manifest.xml` |
| `/dev/trusty-ipc-dev0` and `/dev/tshm` owned by `system`, mode 0660 | `vendor/etc/ueventd.rc` | `/vendor/etc/ueventd.rc` |

`init.recovery.ums9230_6h10.rc` starts them as the ROM does, in this order: when the recovery marks `/data` encrypted it mounts `prodnv` on `/mnt/vendor`, starts the RPMB and prodnv storage proxies, `tee_rpc`, `tsupplicant` and the Trusty service; KeyMint and Gatekeeper start once `tee_rpc` and `tsupplicant` are running; the `/data/vendor` storage proxies start only after the device-encrypted part of `/data` is readable, and stop once all users are decrypted so `/data` can be unmounted.

The recovery reports Android `99.87.36`, security patch `2099-12-31`. KeyMint rejects keys made under a newer patch level than the running system reports; a higher patch level instead makes KeyMint ask for a key upgrade. OrangeFox and SHRP (both on TeamWin vold) write upgraded key blobs only to `/tmp` (`KeyStorage.cpp` in their vold) and run keystore2 on a copy of its database in `/tmp`, so nothing on the phone is rewritten.

Format compatibility with Android 17, checked against the LineageOS 24 sources (`frameworks/base` at `0a8b4cbd4`, `system/vold`, `system/security` at `123cc4a`):

- Lock screen: the phone has no Weaver HAL, so the PIN goes through the Gatekeeper path. In Android 17 that path is unchanged from Android 14: same synthetic password blob versions (V1-V3), same `PasswordData` layout, scrypt parameters, `secdiscardable` transform, protector key alias and `fbe-key` derivation. Only the Weaver path changed, which this phone does not use.
- vold key storage: same file names and versions, same keystore-wrapped key format; metadata encryption on a single `userdata` device uses the same key directory layout.
- keystore2 database: Android 17 writes schema version 2. OrangeFox 16 reads version 2 natively. SHRP 12.1 (TeamWin `android-12.1` keystore2) knows version 1, but its upgrade loop only runs upward, keeps the stored version and reads the same tables; it works on a copy in `/tmp`.
- KeyMint version: the stock HAL serves KeyMint 2; SHRP 12.1 keystore2 speaks KeyMint 1, which a version 2 service still answers (AIDL interfaces stay backward compatible).

Each of the last two rows was found on the phone. libvintf ignores the fragments when no base `manifest.xml` exists, so servicemanager refuses KeyMint and Trusty and keystore2 panics on registration. Without `android.hidl.manager` in the framework manifest hwservicemanager stops itself and the HIDL gatekeeper cannot register, which shows as `failed to get gatekeeper service` on a PIN attempt. Android's ueventd no longer parses `/ueventd.<hardware>.rc`, so the device rules live in `/vendor/etc/ueventd.rc`; otherwise `/dev/trusty-ipc-dev0` stays root-only and `tee_rpc` exits with status 8.

OrangeFox on LineageOS 24 with a PIN set unlocked `/data` on the phone on 2026-11-03: `Data successfully decrypted`, `/data/media/0` file names readable.

## Things to know before flashing

- **Normal boot mounts the system partitions without AVB checks.** The first-stage fstab in this image has no `avb=` flags, the same as the LineageOS `vendor_boot`, so it needs the unlocked bootloader and non-enforcing `vbmeta` below.
- **Only one recovery fits.** Lineage Recovery, the stock Meizu recovery, OrangeFox and SHRP all live in `vendor_boot` and replace each other. Flashing one removes the other.
- **ROM updates overwrite it.** Anything that writes `vendor_boot` (a LineageOS ZIP or OTA, a stock firmware flash) replaces OrangeFox or SHRP with the recovery bundled in that image. A/B updates write the inactive slot, so after such an update the next boot runs the recovery from the new slot. OrangeFox reflashes itself after it installs a ROM ZIP; after an OTA from Android, or with SHRP, flash the recovery again if you want to keep it.
- **`/data` decryption is proven for OrangeFox only.** See [Decryption](#decryption). SHRP has not been tested on the phone; ADB sideload, microSD and USB OTG do not depend on `/data`.
- **Unlocked bootloader required.** The image is signed with the AOSP test key. The bootloader must be unlocked and `vbmeta` must not enforce verification, exactly as for the LineageOS builds of this phone.
- **Unverified on hardware:** everything in the phone test column of [Features](#features), and slot switching through the AOSP boot control HAL. Assumed values: screen height 1600, USB OTG block device `/dev/block/sdg1`.

## Flashing

Keep the full backup of the phone (`vendor_boot_a.bin` from the dump) before you start.

> **Read this first: the bootloader only boots a vendor_boot carrying the Meizu AVB blob.**
> `fastboot flash` and `fastboot boot` both fail on this phone (`Status read failed`), and a
> `vendor_boot` whose embedded vbmeta is signed with a test key stops at the Meizu logo on
> unlock check, with or without `fastboot --disable-verification`.
> Releases from r20 on are resealed in CI with the stock blob
> (`prebuilt/vendor_boot.avb.vbmeta`, sha256 `06daaf6e...`, key `4fce36c7...`, rollback index
> `1790812800`) by `tools/reseal_stock_avb.py`; the ramdisk itself stays as built.
> Evidence and every attempt: [`docs/AVB-FINDINGS.md`](docs/AVB-FINDINGS.md).

Write the image in Unisoc download mode, the only path that writes reliably here:

```sh
# phone off -> hold Volume Up -> plug USB, keep holding until the port appears
lsusb | grep 1782:4d00
cd ~/re/mblu21/tools/linux
./spd_dump --wait 600 exec_addr 0x65015f08 fdl fdl1-dl.bin 0x65000800 \
    fdl fdl2-dl.bin 0x9efffe00 exec w vendor_boot_a /path/to/mblu21-...-vendor_boot.img reset
```

With root (`adb root` or `su -c`) the same write is a plain `dd` and needs no buttons:

```sh
adb push mblu21-...-vendor_boot.img /data/local/tmp/vb.img
adb shell su -c "dd if=/data/local/tmp/vb.img of=/dev/block/by-name/vendor_boot_a bs=1048576"
printf 'boot-recovery' > /dev/block/by-name/misc   # or: adb reboot recovery
```

1. Download `...-vendor_boot.img` and its `.sha256` from a release and check it:
   ```sh
   sha256sum -c mblu21-*-vendor_boot.img.sha256
   ```
2. Write it with `spd_dump` (download mode) or `dd` (root), as shown above; write
   `vendor_boot_b` as well when you want the recovery after an A/B update.
3. Point the boot-control block at recovery (`printf 'boot-recovery' > /dev/block/by-name/misc`)
   or run `adb reboot recovery`, then start the phone with the power button.
   `fastboot reboot recovery` only works when `fastboot flash` already works, which it does not here.

OrangeFox releases also carry an installer ZIP. Installed from OrangeFox (or another recovery), it writes its `recovery.img` to **both** `vendor_boot_a` and `vendor_boot_b`; CI checks that this `recovery.img` is byte-identical to the released `vendor_boot.img`. Of the helper scripts inside the ZIP only `flash-whole-image.sh`/`.bat` work on this phone: `flash-ramdisk.*` expect a separate recovery ramdisk fragment, which this single-fragment layout does not have. OrangeFox ZIPs from releases r4, r7, r8 and r11 cannot install (they were built in ramdisk mode and abort before writing anything); use their `vendor_boot.img` instead.

## Going back

- **Stock recovery:** write `vendor_boot_a.bin` from the backup back to `vendor_boot_a` in download mode (or with `dd` as root), then clear `misc` with `misc.bin` from the same backup.
- **Lineage Recovery:** flash `vendor_boot.img` from the LineageOS build of this phone to the same slot.
- **From OrangeFox or SHRP itself:** Install, Install Image, pick the image, target `Vendor Boot (recovery)`.

If the phone no longer boots at all after flashing, flash the stock `vendor_boot_a.bin` from the bootloader; the bootloader itself is not touched by this image.

## Building

CI does the builds: `.github/workflows/build.yml` runs a matrix of OrangeFox (`fox_16.0`) and SHRP-Reborn (`shrp-12.1`) on every push to `main` and on manual dispatch, then publishes a pre-release per flavour with the image, its SHA-256, the check report and the pinned revision of every synced project (`*-manifest.xml`, from `repo manifest -r`, taken before the local patches in `patches/` are applied, so every revision exists upstream; OrangeFox also its installer ZIP). The `OrangeFox/sync` script is pinned to a commit in `.github/scripts/build.sh`, and `repo` comes from the Ubuntu package with signature verification on. Builds run with a read-only token; only the separate publish job can write releases.

Manifest choice: the newest branch of each project that can build a header v4 `vendor_boot` with decryption.

- OrangeFox: `fox_16.0` (Android 16, `android-16.0.0_r1`), the newest OrangeFox manifest and the only one whose keystore2 already uses the Android 17 database version. It builds with `lunch twrp_mblu21-bp2a-eng`.
- SHRP-Reborn: `shrp-12.1` (Android 12.1, `android-12.1.0_r4`), the only SHRP-Reborn manifest. Its recovery repository also has an `android-14` branch, but there is no manifest, `vendor/shrp`, `vendor/twrp` or `build` branch to build it with. Android 12.1 already supports header v4 `vendor_boot` (vendor bootconfig, ramdisk table) and merging the recovery into the vendor ramdisk, and SHRP uses TeamWin's `android-12.1` vold and keystore2. It builds with `lunch twrp_mblu21-eng`. SHRP's flashable ZIP step only runs for `recoveryimage`/`bootimage`, so SHRP releases contain the `vendor_boot.img` only.

SHRP runs in Express mode (`SHRP_EXPRESS`, `SHRP_EXPRESS_USE_DATA`): theme and lock settings live in `/data/unencrypted/etc/shrp`. Without Express, SHRP saves them by repacking `boot` and writing it back to `boot_<slot>`, which on this phone holds the GKI kernel, not the recovery.

Local build for SHRP: needs `python2.7` on `PATH` (`.github/scripts/python2.sh` builds it), `repo init -u https://github.com/SHRP-Reborn/manifest.git -b shrp-12.1`, `repo sync`, then apply the local patches before building, otherwise the first-stage `fsck.f2fs` is packed non-executable:

```sh
git -C system/core am device/meizu/mblu21/patches/shrp-12.1/system/core/*.patch
```

Then skip `orangefox_vars.sh` and `lunch twrp_mblu21-eng`. Local build for OrangeFox also applies its local patch: `fox_16.0` minuitwrp ships the atomic DRM backend written for Qualcomm SDE, which returns no surface on Unisoc `sprd_drm`, so without the patch the recovery crash-loops on the boot logo:

```sh
git clone https://gitlab.com/OrangeFox/sync.git && cd sync && ./orangefox_sync.sh --branch 16.0 --path ~/fox16 && cd ~/fox16
git clone https://github.com/tickernelz/android_device_meizu_mblu21-recovery device/meizu/mblu21
git -C bootable/recovery am ../../device/meizu/mblu21/patches/fox_16.0/bootable/recovery/*.patch
export ALLOW_MISSING_DEPENDENCIES=true
source device/meizu/mblu21/orangefox_vars.sh
source build/envsetup.sh
lunch twrp_mblu21-bp2a-eng
mka vendorbootimage
python3 device/meizu/mblu21/tools/vendor_boot_check.py out/target/product/mblu21/vendor_boot.img \
  --reference device/meizu/mblu21/prebuilt/stock_vendor_boot.json --flavor orangefox \
  --rom-fstab device/meizu/mblu21/prebuilt/fstab.rom.ums9230_6h10 \
  --zip out/target/product/mblu21/OrangeFox-*.zip
```

## Sources

- Stock files in `prebuilt/` and `recovery/root/` (`vendor/etc/ueventd.rc`, touch modules) come from the M416H firmware; `first_stage_ramdisk/fstab.ums9230_6h10` is the stock file without its `avb=`/`avb_keys=` flags. They belong to Meizu and Unisoc and are included only so the device keeps booting with this image.
- LineageOS device tree: [tickernelz/android_device_meizu_mblu21](https://github.com/tickernelz/android_device_meizu_mblu21).

Licensed under Apache-2.0, except the stock firmware files listed above.
