#!/usr/bin/env bash
set -eu

# ❯ tree
# .
# ├── Dairantou Smash Brothers DX (Japan) (Rev 2) [GALJ01]
# │   └── Dairantou Smash Brothers DX (Japan) (Rev 2).bca
# │   └── Dairantou Smash Brothers DX (Japan) (Rev 2).iso
# │   └── Dairantou Smash Brothers DX (Japan) (Rev 2)-dumpinfo.txt
# ├── Pokemon Colosseum (Europe) [GC6P01]
# │   └── Pokemon Colosseum (Europe).bca
# │   └── Pokemon Colosseum (Europe).iso
# │   └── Pokemon Colosseum (Europe)-dumpinfo.txt
# ...
# └── Tales of Symphonia (France) [GQSFAF]
#     ├── Tales of Symphonia (France) (Disc 1).bca
#     ├── Tales of Symphonia (France) (Disc 1).iso
#     ├── Tales of Symphonia (France) (Disc 1)-dumpinfo.txt
#     └── Tales of Symphonia (France) (Disc 2).bca
#     └── Tales of Symphonia (France) (Disc 2).iso
#     └── Tales of Symphonia (France) (Disc 2)-dumpinfo.txt

if [[ $# != 2 ]]; then
	printf 'Usage: %s SOURCE_DIR DEST_DIR (e.g. /Volumes/RVLOADER/games)\n' "${0##*/}" >&2
	exit 2
fi

if [[ ! -d $1 ]]; then
	printf 'Source directory not found: %s\n' "$1" >&2
	exit 1
fi
source_dir=$(realpath -- "$1")
mkdir -p -- "$2"
dest_dir=$(realpath -- "$2")
if [[ ${source_dir} -ef ${dest_dir} ]]; then
	printf 'Source and destination must be different directories\n' >&2
	exit 1
fi

shopt -s nullglob
for iso in "${source_dir}"/*/*.iso; do
	[[ -f ${iso} ]] || continue
	dir=${iso%/*}
	case "${iso##*/}" in
		*"(Disc 2).iso") newname=disc2.iso ;;
		*) newname=game.iso ;;
	esac

	game_dir="${dest_dir}/${dir##*/}"
	if [[ -L ${game_dir} ]]; then
		printf 'Refusing to write through a symlink: %s\n' "${game_dir}" >&2
		exit 1
	fi
	output="${game_dir}/${newname}"
	if [[ -e ${output} || -L ${output} ]]; then
		printf 'Skipping existing file: %s\n' "${output}"
		continue
	fi
	mkdir -p -- "${game_dir}"
	printf 'Copying %s -> %s\n' "${iso##*/}" "${output}"
	(
		tmp=$(mktemp "${game_dir}/.iso.XXXXXX")
		trap 'rm -f -- "${tmp}"' EXIT
		cp -- "${iso}" "${tmp}"
		mv -n -- "${tmp}" "${output}"
	)
done
