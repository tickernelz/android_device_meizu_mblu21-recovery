#!/usr/bin/env bash
set -euo pipefail

version=2.7.18
sha256=da3080e3b488f648a3d7a4560ddee895284c3380b11d6de75edb986526b9a814
prefix=/opt/python2

work="$(mktemp -d)"
curl -fsSL "https://www.python.org/ftp/python/$version/Python-$version.tgz" -o "$work/python.tgz"
echo "$sha256  $work/python.tgz" | sha256sum -c -
tar -xzf "$work/python.tgz" -C "$work"
cd "$work/Python-$version"
./configure --prefix="$prefix" > /dev/null
make -j"$(nproc)" > /dev/null 2>&1
sudo make altinstall > /dev/null 2>&1
mkdir -p "$HOME/bin"
ln -sf "$prefix/bin/python2.7" "$HOME/bin/python2.7"
ln -sf "$prefix/bin/python2.7" "$HOME/bin/python2"
cd /
rm -rf "$work"
"$HOME/bin/python2" --version
