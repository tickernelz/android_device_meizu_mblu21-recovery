#!/usr/bin/env bash
set -euo pipefail

root_dev="$(df --output=source / | tail -1)"
mnt_dev="$(df --output=source /mnt | tail -1)"

if [ "$root_dev" = "$mnt_dev" ]; then
  sudo mkdir -p "$WORK"
else
  root_free="$(df -BG --output=avail / | tail -1 | tr -dc 0-9)"
  mnt_free="$(df -BG --output=avail /mnt | tail -1 | tr -dc 0-9)"
  sudo fallocate -l "$(( root_free - 6 ))G" /pv-root.img
  sudo fallocate -l "$(( mnt_free - 2 ))G" /mnt/pv-mnt.img
  root_loop="$(sudo losetup --find --show /pv-root.img)"
  mnt_loop="$(sudo losetup --find --show /mnt/pv-mnt.img)"
  sudo pvcreate -q "$root_loop" "$mnt_loop"
  sudo vgcreate -q buildvg "$root_loop" "$mnt_loop"
  sudo lvcreate -q -l 100%FREE -n work buildvg
  sudo mkfs.ext4 -q -m 0 -E lazy_itable_init=1,lazy_journal_init=1 /dev/buildvg/work
  sudo mkdir -p "$WORK"
  sudo mount -o noatime /dev/buildvg/work "$WORK"
fi
sudo chown "$USER:$USER" "$WORK"
df -h / /mnt "$WORK"
