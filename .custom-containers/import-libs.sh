#!/bin/bash

set -euo pipefail

BIN_PATH="${1:?Usage: $0 <binary_path>}"
TARGET_DIR="${LIB_DEST:-/lib/dyn}"

mkdir -p "$TARGET_DIR"

ldd "$BIN_PATH" \
	| awk '{gsub(".*/","",$1); print $1}' \
	| while read -r lib; do
		# Skip virtual libs (like linux-vdso.so.1)
		if [[ $lib =~ ^linux-.*\.so.*$ ]]; then
			echo "Skipping virtual lib: $lib"
			continue
		fi

		LIB_PATH=$(find /lib /usr/lib -name "$lib" -print -quit)

		if [[ -z $LIB_PATH ]]; then
			echo "Error: Could not find library '$lib'" >&2
			exit 1
		fi

		cp -L "$LIB_PATH" "$TARGET_DIR"
	done
