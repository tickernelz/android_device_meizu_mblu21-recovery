#!/usr/bin/env bash
set -euo pipefail

zip_file="$1"
image="$2"
signer="$3"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

cp "$image" "$work/recovery.img"
zip -q -d "$zip_file" 'META-INF/MANIFEST.MF' 'META-INF/CERT.SF' 'META-INF/CERT.RSA'
(cd "$work" && zip -q -0 "$zip_file" recovery.img)
java -jar "$signer" "$zip_file" "$work/signed.zip"
mv "$work/signed.zip" "$zip_file"
unzip -p "$zip_file" recovery.img | cmp - "$image"
