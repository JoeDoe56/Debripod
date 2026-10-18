#!/usr/bin/env sh
# Build sfgl and vendor it into DebriPod.
#   Scripts/sync-sfgl.sh [path-to-sfgl-checkout]   (default: ../sfgl)
set -eu
here="$(cd "$(dirname "$0")/.." && pwd)"
sfgl="${1:-$here/../sfgl}"
dest="$here/debripod/static/vendor/sfgl"
(cd "$sfgl" && npm install --silent && npm run --silent build)
mkdir -p "$dest/licenses"
cp "$sfgl/dist/sfgl.iife.js" "$sfgl/dist/sfgl.iife.js.map" "$sfgl/dist/sfgl.css" "$sfgl/LICENSE" "$sfgl/NOTICE.md" "$dest/"
cp -R "$sfgl/licenses/." "$dest/licenses/"
version="$(cd "$sfgl" && node -p "require('./package.json').version")"
commit="$(cd "$sfgl" && git rev-parse --short HEAD 2>/dev/null || echo unknown)"
printf 'sfgl %s (%s)\n' "$version" "$commit" > "$dest/VERSION"
echo "vendored sfgl $version ($commit) into $dest"
