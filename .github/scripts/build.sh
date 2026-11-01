#!/usr/bin/env bash
set -euo pipefail

src="$WORK/src"
jobs="$(nproc)"

case "$FLAVOR" in
  twrp)
    release=ap2a
    mkdir -p "$src"
    cd "$src"
    repo init --depth=1 --no-repo-verify -u https://github.com/minimal-manifest-twrp/platform_manifest_twrp_aosp.git -b "$MANIFEST_BRANCH" -g default,-mips,-darwin,-notdefault
    repo sync -c -j"$jobs" --force-sync --no-clone-bundle --no-tags --optimized-fetch --prune
    ;;
  orangefox)
    release=bp2a
    git clone --depth 1 https://gitlab.com/OrangeFox/sync.git "$WORK/fox-sync"
    cd "$WORK/fox-sync"
    ./orangefox_sync.sh --branch "${MANIFEST_BRANCH#fox_}" --path "$src"
    ;;
  *)
    echo "unknown flavor: $FLAVOR" >&2
    exit 1
    ;;
esac

mkdir -p "$src/device/meizu"
rsync -a --delete --exclude .git --exclude .github "$GITHUB_WORKSPACE/tree/" "$src/device/meizu/mblu21/"
df -h "$WORK"

cd "$src"
export ALLOW_MISSING_DEPENDENCIES=true
if [ "$FLAVOR" = orangefox ]; then
  source device/meizu/mblu21/orangefox_vars.sh
fi
set +u
source build/envsetup.sh
lunch "twrp_mblu21-${release}-eng"
set -u
mka vendorbootimage
ls -l out/target/product/mblu21/
df -h "$WORK"
