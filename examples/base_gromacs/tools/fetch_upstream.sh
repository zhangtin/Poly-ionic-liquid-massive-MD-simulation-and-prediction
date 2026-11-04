#!/usr/bin/env bash
# Re-fetch the unmodified upstream GROMACS files used by this base project and
# verify them against the checksums recorded in docs/EXAMPLE_SOURCE.md.
# PROJECT-CREATED helper. Requires git and network access to github.com.
#
# Usage: bash tools/fetch_upstream.sh [DEST_DIR]   (default: ./_upstream_check)
set -euo pipefail

TAG="v2025.5"
REPO="https://github.com/gromacs/gromacs.git"   # official GitHub mirror of gitlab.com/gromacs/gromacs
DEST="${1:-_upstream_check}"

if [[ -e "$DEST" ]]; then
    echo "ERROR: $DEST already exists" >&2
    exit 1
fi

git clone --quiet --depth 1 --branch "$TAG" --filter=blob:none --sparse "$REPO" "$DEST"
git -C "$DEST" sparse-checkout set --no-cone \
    /share/top/spc216.gro \
    /share/top/oplsaa.ff/forcefield.itp \
    /share/top/oplsaa.ff/ffnonbonded.itp \
    /share/top/oplsaa.ff/ffbonded.itp \
    /share/top/oplsaa.ff/spce.itp \
    /COPYING
echo "commit: $(git -C "$DEST" rev-parse HEAD)"

cd "$DEST"
sha256sum -c - <<'EOF'
dcb2c65552058a5083fddc5a4bb3187b1eac6c46e3acf038643ec2ec9f147620  share/top/spc216.gro
6eb8f0d08684e1ac6f525bb323eae75ed197b2980ddfde975a24ca1a8c931d06  share/top/oplsaa.ff/forcefield.itp
fdf072dac9900c039b58e21323ce621b2112dc86c46a4b5e49e1398ae5d3b9f0  share/top/oplsaa.ff/ffnonbonded.itp
145e6924f52fae7e93108fa3d674f31a53aea10c80b13dd89abf0b011adfd4fa  share/top/oplsaa.ff/ffbonded.itp
e733446e1c7bcf42e21ba2ff84cc57d8d603210218faa5203b3f078026d80682  share/top/oplsaa.ff/spce.itp
b634ab5640e258563c536e658cad87080553df6f34f62269a21d554844e58bfe  COPYING
EOF
