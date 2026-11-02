#!/usr/bin/env bash
set -euo pipefail

src="$WORK/src"
jobs="$(nproc)"

case "$FLAVOR" in
  orangefox)
    lunch_target=twrp_mblu21-bp2a-eng
    git clone --depth 1 https://gitlab.com/OrangeFox/sync.git "$WORK/fox-sync"
    cd "$WORK/fox-sync"
    ./orangefox_sync.sh --branch "${MANIFEST_BRANCH#fox_}" --path "$src"
    ;;
  shrp)
    lunch_target=twrp_mblu21-eng
    mkdir -p "$src"
    cd "$src"
    repo init --depth=1 --no-repo-verify -u https://github.com/SHRP-Reborn/manifest.git -b "$MANIFEST_BRANCH" -g default,-mips,-darwin,-notdefault
    repo sync -c -j"$jobs" --force-sync --no-clone-bundle --no-tags --optimized-fetch --prune
    ;;
  *)
    echo "unknown flavor: $FLAVOR" >&2
    exit 1
    ;;
esac

mkdir -p "$src/device/meizu"
rsync -a --delete --exclude .git --exclude .github "$GITHUB_WORKSPACE/tree/" "$src/device/meizu/mblu21/"
df -h "$WORK"

free_gb="$(df -BG --output=avail "$WORK" | tail -1 | tr -dc 0-9)"
extra_swap=$(( free_gb - 22 ))
if [ "$extra_swap" -gt 24 ]; then
  extra_swap=24
fi
if [ "$extra_swap" -ge 4 ]; then
  sudo fallocate -l "${extra_swap}G" "$WORK/swap2"
  sudo chmod 600 "$WORK/swap2"
  sudo mkswap "$WORK/swap2" > /dev/null
  sudo swapon -p 0 "$WORK/swap2"
fi
swapon --show
while sleep 60; do free -m | awk -v t="$(date -u +%T)" '/Mem:/{m=$3} /Swap:/{s=$3} END{print "mem " t " used=" m "M swap=" s "M"}'; done &

cd "$src"
export ALLOW_MISSING_DEPENDENCIES=true
if [ "$FLAVOR" = orangefox ]; then
  source device/meizu/mblu21/orangefox_vars.sh
fi
set +u
source build/envsetup.sh
lunch "$lunch_target"
mka vendorbootimage
set -u
ls -l out/target/product/mblu21/
df -h "$WORK"
