#!/bin/sh

# On alpine run:
# > setup-interfaces
# > rc-service networking restart
# > echo 1 > /proc/sys/net/ipv6/conf/all/disable_ipv6 # if needed
# setup-apkrepos
# > apk add sfdisk e2fsprogs-extra

set -eu

# renovate: datasource=github-tags depName=openwrt/openwrt extractVersion=^v(?<version>\d+\.\d+\.\d+)$
VERSION=25.12.5
IMAGE="fedex-openwrt-$VERSION-ext4-combined-efi.img.gz"
URL="https://github.com/vic1707/homelab/releases/download/openwrt-fedex-$VERSION/$IMAGE"

die() {
	printf 'error: %s\n' "$*" >&2
	exit 1
}

usage() {
	printf 'usage: curl -fsSL https://raw.githubusercontent.com/vic1707/homelab/main/devices/fedex/install.sh | sh -s -- /dev/nvme0n1\n'
	printf 'usage: wget -qO- https://raw.githubusercontent.com/vic1707/homelab/main/devices/fedex/install.sh | sh -s -- /dev/nvme0n1\n'
}

part() {
	case "$disk" in
		*mmcblk* | *nvme*) printf '%sp%s\n' "$disk" "$1" ;;
		*) printf '%s%s\n' "$disk" "$1" ;;
	esac
}

grow_rootfs() {
	root_part="$(part 2)"
	for cmd in sfdisk e2fsck resize2fs; do
		command -v "$cmd" > /dev/null 2>&1 || {
			printf 'Skipping rootfs grow: %s is missing (on Alpine: apk add sfdisk e2fsprogs-extra).\n' "$cmd" >&2
			return 0
		}
	done

	printf ',+\n' | sfdisk -N 2 "$disk"
	partprobe "$disk" > /dev/null 2>&1 || blockdev --rereadpt "$disk" > /dev/null 2>&1 || true
	e2fsck -f -y "$root_part"
	resize2fs "$root_part"
}

[ "${1:-}" != "" ] || {
	usage
	exit 2
}
[ "$(id -u)" = 0 ] || die "run as root"
[ ! -f /etc/openwrt_release ] || die "boot a live ISO; refusing to overwrite running OpenWrt"

disk="$1"
[ -b "$disk" ] || die "not a block device: $disk"

for cmd in wget dd gzip mktemp mount; do
	command -v "$cmd" > /dev/null 2>&1 || die "$cmd is required"
done

mounted="$(
	mount | while IFS= read -r line; do
		src=${line%% on *}
		case "$src" in
			"$disk" | "$disk"[0-9]* | "$disk"p[0-9]*) printf '%s\n' "$src" ;;
		esac
	done
)"
[ -z "$mounted" ] || die "target has mounted partitions: $mounted"

printf 'This will erase %s and install %s. Type YES: ' "$disk" "$IMAGE" > /dev/tty
IFS= read -r answer < /dev/tty
[ "$answer" = YES ] || die "aborted"

tmp="$(mktemp "${TMPDIR:-/tmp}/fedex-openwrt.XXXXXX")"
trap 'rm -f "$tmp"' EXIT INT TERM

wget -O "$tmp" "$URL"
gzip -t "$tmp"
gzip -dc "$tmp" | dd of="$disk" bs=16M conv=fsync
sync
grow_rootfs
sync

printf 'Installed %s to %s. Reboot, then SSH to root@192.168.255.1 on RJ45-2.\n' "$IMAGE" "$disk"
