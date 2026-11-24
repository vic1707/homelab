#!/usr/bin/env bash
set -eu

# .
# ├── Dairantou Smash Brothers X (Japan) (Rev 1) [RSBJ01]
# │   ├── Dairantou Smash Brothers X (Japan) (Rev 1)-dumpinfo.txt
# │   ├── Dairantou Smash Brothers X (Japan) (Rev 1).bca
# │   └── Dairantou Smash Brothers X (Japan) (Rev 1).iso
# ├── Last Story, The (Europe) [SLSP01]
# │   ├── Last Story, The (Europe)-dumpinfo.txt
# │   ├── Last Story, The (Europe).bca
# │   └── Last Story, The (Europe).iso
# ...
# └── Xenoblade Chronicles (Europe) [SX4P01]
#     ├── Xenoblade Chronicles (Europe)-dumpinfo.txt
#     ├── Xenoblade Chronicles (Europe).bca
#     └── Xenoblade Chronicles (Europe).iso

if [[ $# != 2 ]]; then
	printf 'Usage: %s SOURCE_DIR DEST_DIR (e.g. /Volumes/RVLOADER/wbfs)\n' "${0##*/}" >&2
	exit 2
fi

if [[ ! -d $1 ]]; then
	printf 'Source directory not found: %s\n' "$1" >&2
	exit 1
fi
source_dir=$(realpath -- "$1")
if ! command -v wit > /dev/null; then
	printf 'wit is required to convert Wii ISOs\n' >&2
	exit 1
fi
mkdir -p -- "$2"
dest_dir=$(realpath -- "$2")
if [[ ${source_dir} -ef ${dest_dir} ]]; then
	printf 'Source and destination must be different directories\n' >&2
	exit 1
fi

shopt -s nullglob
id_pattern='\[([A-Z0-9]{6})\]$'
for iso in "${source_dir}"/*/*.iso; do
	[[ -f ${iso} ]] || continue
	dir=${iso%/*}
	game=${dir##*/}
	if [[ ! ${game} =~ ${id_pattern} ]]; then
		printf 'Missing [GAMEID] at end of folder name: %s\n' "${dir}" >&2
		exit 1
	fi
	id=${BASH_REMATCH[1]}
	game_dir="${dest_dir}/${game}"
	if [[ -L ${game_dir} ]]; then
		printf 'Refusing to write through a symlink: %s\n' "${game_dir}" >&2
		exit 1
	fi
	output="${game_dir}/${id}.wbfs"
	parts=("${game_dir}/${id}".wbf[0-9]*)
	if [[ -e ${output} || -L ${output} || -n ${parts[0]:-} ]]; then
		printf 'Skipping existing WBFS or split part: %s\n' "${output}"
		continue
	fi
	mkdir -p -- "${game_dir}"
	wit copy --esc '' --wbfs --split --update -- "${iso}" "${output}"
	if [[ ! -s ${output} ]]; then
		printf 'No WBFS produced: %s\n' "${output}" >&2
		exit 1
	fi
done
