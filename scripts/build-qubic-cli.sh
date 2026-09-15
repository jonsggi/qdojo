#!/usr/bin/env bash
# Build qubic-cli (the reference implementation, the only signer qdojo uses
# today) from a pinned upstream commit into ~/.qdojo/qubic-cli.
set -euo pipefail
PIN="${QUBIC_CLI_PIN:-d8fb56459ca0}"
DEST="${1:-$HOME/.qdojo}"
SRC="$DEST/src/qubic-cli"
mkdir -p "$DEST/src"
if [ ! -d "$SRC/.git" ]; then git clone -q https://github.com/qubic/qubic-cli "$SRC"; fi
git -C "$SRC" fetch -q origin
git -C "$SRC" checkout -q "$PIN"
git -C "$SRC" submodule update --init --recursive -q
cmake -S "$SRC" -B "$SRC/build" -DCMAKE_BUILD_TYPE=Release >/dev/null
cmake --build "$SRC/build" -j "$(nproc 2>/dev/null || sysctl -n hw.ncpu)" >/dev/null
install -m 755 "$SRC/build/qubic-cli" "$DEST/qubic-cli"
echo "built $DEST/qubic-cli from qubic-cli $PIN"
