#!/usr/bin/env bash
set -euo pipefail

# Build one device env preset into a sysupgrade image.
# Example: .openwrt-base/build.sh --out-dir dist/openwrt devices/bacon/openwrt.env

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR=""
TEMPLATE_ENV_VARS=(OPENWRT_HOSTNAME)

die() {
	printf 'error: %s\n' "$*" >&2
	exit 1
}

require_nonempty() {
	local source_file="$1" name
	shift
	for name in "$@"; do
		[ -n "${!name-}" ] || die "$source_file must set $name"
	done
}

for cmd in curl envsubst find jq podman shasum; do
	command -v "$cmd" > /dev/null 2>&1 || die "$cmd is required"
done

while [ "$#" -gt 0 ]; do
	case "$1" in
		--out-dir)
			OUT_DIR="${2:?}"
			shift 2
			;;
		-*) die "unknown option: $1" ;;
		*) break ;;
	esac
done

[ "$#" -eq 1 ] || die "exactly one preset file is required"
preset="$1"
[ -f "$preset" ] || die "preset not found: $preset"
# shellcheck disable=SC1090
source "$preset"
require_nonempty "$preset" OPENWRT_VERSION OPENWRT_TARGET OPENWRT_SUBTARGET OPENWRT_PROFILE OPENWRT_BASE OPENWRT_SSH_PUBLIC_KEY
[[ $OPENWRT_VERSION =~ ^[0-9]+[.][0-9]+[.][0-9]+$ ]] || die "$preset must set OPENWRT_VERSION as major.minor.patch"

base_preset="$ROOT/.openwrt-base/$OPENWRT_BASE/preset.env"
[ -f "$base_preset" ] || die "base preset not found: $base_preset"
# shellcheck source=/dev/null
source "$base_preset"
require_nonempty "$base_preset" OPENWRT_BASE_FILES

ssh_key="$ROOT/$OPENWRT_SSH_PUBLIC_KEY"
case "$ssh_key" in *.pub) ;; *) die "SSH public key must be a .pub file: $ssh_key" ;; esac
[ -f "$ssh_key" ] || die "SSH public key not found: $ssh_key"

preset_dir="$(cd -- "$(dirname -- "$preset")" && pwd)"
device="$(basename "$preset_dir")"
hostname="${OPENWRT_HOSTNAME:-$device}"
[[ $hostname =~ ^[A-Za-z0-9]([A-Za-z0-9-]*[A-Za-z0-9])?$ ]] || die "invalid hostname: $hostname"
OPENWRT_HOSTNAME="$hostname"
envsubst_vars=""
for name in "${TEMPLATE_ENV_VARS[@]}"; do
	envsubst_vars="${envsubst_vars}\${$name}"
done
export "${TEMPLATE_ENV_VARS[@]}"

disabled_services="${OPENWRT_BASE_DISABLED_SERVICES:-} ${OPENWRT_DISABLED_SERVICES:-}"
packages="${OPENWRT_BASE_ADD_PACKAGES:-} ${OPENWRT_ADD_PACKAGES:-}"
for package in ${OPENWRT_BASE_REMOVE_PACKAGES:-} ${OPENWRT_REMOVE_PACKAGES:-}; do
	packages="$packages -$package"
done

printf '\n==> %s: %s/%s %s on OpenWrt %s\n' "$device" "$OPENWRT_TARGET" "$OPENWRT_SUBTARGET" "$OPENWRT_PROFILE" "$OPENWRT_VERSION"

work="$preset_dir/.build"
files="$work/files"
build_bin="$work/bin"
out="${OUT_DIR:-$preset_dir/bin}"
rm -rf "$work"

profiles="$(curl -fsSL --retry 3 "https://downloads.openwrt.org/releases/$OPENWRT_VERSION/targets/$OPENWRT_TARGET/$OPENWRT_SUBTARGET/profiles.json")"
printf '%s\n' "$profiles" | jq -e --arg profile "$OPENWRT_PROFILE" '.profiles[$profile]' > /dev/null \
	|| die "$OPENWRT_PROFILE is not present in upstream profiles.json"
for package in ${OPENWRT_BASE_REMOVE_PACKAGES:-} ${OPENWRT_REMOVE_PACKAGES:-}; do
	printf '%s\n' "$profiles" | jq -e --arg profile "$OPENWRT_PROFILE" --arg package "$package" \
		'.default_packages + .profiles[$profile].device_packages | index($package)' > /dev/null \
		|| die "cannot remove non existent $package"
done
for package in ${OPENWRT_BASE_ADD_PACKAGES:-} ${OPENWRT_ADD_PACKAGES:-}; do
	printf '%s\n' "$profiles" | jq -e --arg profile "$OPENWRT_PROFILE" --arg package "$package" \
		'.default_packages + .profiles[$profile].device_packages | index($package) | not' > /dev/null \
		|| die "no need to add $package, already there"
done

mkdir -p "$files/etc/config" "$files/etc/dropbear" "$build_bin" "$out"
cp -a "$ROOT/$OPENWRT_BASE_FILES"/. "$files"/
if [ -d "$preset_dir/files" ]; then
	cp -a "$preset_dir/files"/. "$files"/
fi
if [ "${OPENWRT_EXPAND_ROOT:-0}" = "1" ]; then
	expand_root_url="https://openwrt.org/_export/code/docs/guide-user/advanced/expand_root?codeblock=1"
	expand_root_sha256="4ac1431a833c37e0a8f298f9d50eeeddf35ec0b8513a296892ec6ad6a9d93aba"
	expand_root_source="$work/expand-root.sh"
	curl -fsSL -A "" "$expand_root_url" > "$expand_root_source"
	[ "$(shasum -a 256 "$expand_root_source" | cut -d ' ' -f 1)" = "$expand_root_sha256" ] \
		|| die "expand-root checksum mismatch"
	mkdir -p "$files/etc/uci-defaults"
	expand_root="$files/etc/uci-defaults/60-expand-root"
	expand_root_script="$(< "$expand_root_source")"
	cat > "$expand_root" << EOF
#!/bin/sh

set -eu

if [ -e /etc/uci-defaults/70-rootpt-resize ] && [ -e /etc/uci-defaults/80-rootfs-resize ]; then
	exit 0
fi

$expand_root_script

sh /etc/uci-defaults/70-rootpt-resize || true
EOF
	chmod 0755 "$expand_root"
fi
while IFS= read -r file; do
	cp -p "$file" "$file.tmp"
	envsubst "$envsubst_vars" < "$file" > "$file.tmp"
	mv "$file.tmp" "$file"
done < <(find "$files" -type f ! -name .gitkeep)
find "$files" -name .gitkeep -delete

cp -L "$ssh_key" "$files/etc/dropbear/authorized_keys"
# The imagebuilder container may run as a non-root user in CI. This is a
# public key, so keep the staged copy readable while still not writable.
chmod 0644 "$files/etc/dropbear/authorized_keys"
chmod 0777 "$build_bin"

image="${OPENWRT_IMAGE:-openwrt/imagebuilder:${OPENWRT_TARGET}-${OPENWRT_SUBTARGET}-openwrt-${OPENWRT_VERSION%.*}}"
podman run --rm \
	-e "TARGET=$OPENWRT_TARGET/$OPENWRT_SUBTARGET" \
	-e "VERSION_PATH=releases/$OPENWRT_VERSION" \
	-e "DOWNLOAD_FILE=imagebuilder-.*${OPENWRT_TARGET}-${OPENWRT_SUBTARGET}.Linux-x86_64.tar.[xz|zst]" \
	-e "PROFILE=$OPENWRT_PROFILE" \
	-e "PACKAGES=$packages" \
	-e "FILES=/builder/files" \
	-e "DISABLED_SERVICES=$disabled_services" \
	-v "$files:/builder/files:ro" \
	-e "BIN_DIR=/builder/bin" \
	-v "$build_bin:/builder/bin" \
	"$image" /bin/bash -lc '[ -d ./scripts ] || ./setup.sh; make image PROFILE="$PROFILE" PACKAGES="$PACKAGES" FILES="$FILES" BIN_DIR="$BIN_DIR" DISABLED_SERVICES="$DISABLED_SERVICES"'

artifact_glob="${OPENWRT_ARTIFACT_GLOB:-*sysupgrade*.bin}"
image_count=0
artifact=""
while IFS= read -r candidate; do
	image_count=$((image_count + 1))
	artifact="$candidate"
done < <(find "$build_bin" -type f -name "$artifact_glob" | sort)
[ "$image_count" -eq 1 ] || die "$device produced $image_count matching $artifact_glob"

final="$out/$device-openwrt-$OPENWRT_VERSION-${OPENWRT_ARTIFACT_NAME:-sysupgrade.${artifact##*.}}"
cp "$artifact" "$final"
rm -rf "$work"
printf 'Built %s\n' "$final"
