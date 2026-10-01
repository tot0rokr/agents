#!/bin/bash
# Render a web page in headless Chromium and report what a browser shows.
#
# Chromium runs in the official Playwright container, so the host needs only
# docker: no browser, no system libraries, no root. Outputs (screenshot and
# visible text) land in HEADLESS_BROWSER_OUT; the JSON report goes to stdout.
#
#   browse.sh <url> [--name N] [--wait MS] [--wait-for SELECTOR] [--full-page]
#   HEADLESS_BROWSER_STATE=<file> browse.sh <url>   # a session the user saved
set -euo pipefail

PLAYWRIGHT_VERSION=${PLAYWRIGHT_VERSION:-1.63.0}
IMAGE=${HEADLESS_BROWSER_IMAGE:-headless-browser:$PLAYWRIGHT_VERSION}
OUT=${HEADLESS_BROWSER_OUT:-${TMPDIR:-/tmp}/headless-browser-$(id -un)}
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
# The container runs in UTC; show page times in the host's zone instead, as
# a local browser would. No /etc/localtime means the host is on UTC too.
TIMEZONE=${TZ:-$(readlink /etc/localtime 2>/dev/null | sed 's|.*/zoneinfo/||' || true)}

[ $# -ge 1 ] || { sed -n '2,10p' "$0" >&2; exit 2; }
command -v docker >/dev/null || { echo "docker is required" >&2; exit 1; }
mkdir -p "$OUT"

# First run builds the image once (official Playwright base + the Python
# package); build output goes to stderr so stdout stays the JSON report.
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
	echo "building $IMAGE (one-time)..." >&2
	docker build -q -t "$IMAGE" \
		--build-arg PLAYWRIGHT_VERSION="$PLAYWRIGHT_VERSION" "$HERE" >&2
fi

mounts=(-v "$HERE/browse.py:/opt/browse.py:ro" -v "$OUT:/out")
state=()
if [ -n "${HEADLESS_BROWSER_STATE:-}" ]; then
	[ -r "$HEADLESS_BROWSER_STATE" ] || {
		echo "cannot read $HEADLESS_BROWSER_STATE" >&2
		exit 1
	}
	mounts+=(-v "$(realpath "$HEADLESS_BROWSER_STATE"):/state.json:ro")
	state=(--storage-state /state.json)
fi

# --network host: resolve and reach exactly what this host can.
# --ipc host: Chromium needs more shared memory than docker's default.
# --init: python as PID 1 would ignore SIGTERM and outlive an interrupted run.
exec docker run --rm --init --network host --ipc host \
	--user "$(id -u):$(id -g)" -e HOME=/tmp "${mounts[@]}" "$IMAGE" \
	python3 /opt/browse.py --out /out --host-out "$OUT" \
	--timezone "$TIMEZONE" "${state[@]}" "$@"
