#!/bin/sh
set -eu

usage() {
	printf 'usage: %s INPUT_BIOS OUTPUT_BIOS\n' "$0" >&2
}

if [ "${1:-}" = "-h" ] || [ "${1:-}" = "--help" ]; then
	usage
	exit 0
fi

[ "$#" -eq 2 ] || { usage; exit 2; }

input="$(realpath "$1")"
output="$(realpath -m "$2")"
key=/opt/secureflash/secureflash.key.pem

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT INT TERM

unsigned="$tmp/rebar.bin"
signed="$tmp/signed.bin"

echo '[1/3] Inserting ReBarDxe...'
ReBarInsert "$input" /opt/rebar/ReBarDxe.ffs "$unsigned"

printf 'ReBar image SHA256: '
sha256sum "$unsigned" | cut -d' ' -f1

echo '[2/3] Re-signing SecureFlash...'
secureflash-sign \
	--reference "$input" \
	--key "$key" \
	--output "$signed" \
	"$unsigned"

printf 'Signed image SHA256: '
sha256sum "$signed" | cut -d' ' -f1

printf '[3/3] Verifying with SUM...\n'
if ! sum_output="$(sum --journal_path /tmp -c GetBiosInfo --file_only --file "$signed" 2>&1)"; then
	echo "$sum_output"
	echo 'SUM validation failed' >&2
	exit 1
fi

echo "$sum_output"

images="$(printf '%s\n' "$sum_output" | grep -c '^Local BIOS image file' || true)"
signed_images="$(printf '%s\n' "$sum_output" | grep -Ec 'FW image[.]+Signed[[:space:]]*$' || true)"
secureflash_images="$(printf '%s\n' "$sum_output" | grep -Ec 'Signed Key[.]+SecureFlash[[:space:]]*$' || true)"

if [ "$images" -eq 0 ] ||
   [ "$signed_images" -ne "$images" ] ||
   [ "$secureflash_images" -ne "$images" ]; then
	echo 'SUM did not report Signed / SecureFlash for every BIOS image' >&2
	exit 1
fi

cp "$signed" "$output"

echo 'SUCCESS'
echo "Output: $output"
sha256sum "$output"
