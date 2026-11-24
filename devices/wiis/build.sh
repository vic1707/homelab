#!/usr/bin/env bash
set -euo pipefail

usage() {
	cat << EOF
Usage:
  ${0##*/} extract PROFILE BACKUP                Save a SOPS-encrypted PROFILE/seed.yml
  ${0##*/} build PROFILE                        Build from PROFILE/seed.yml and recipe.yml
  ${0##*/} build PROFILE --from-backup BACKUP     Build without saving a seed

PROFILE is an existing directory. BACKUP is a BootMii NAND dump with embedded keys.
Builds write PROFILE/out/sd/nand.bin and the rest of the restore bundle to a new PROFILE/out.
Both seed.yml and recipe.yml may be plaintext or SOPS-encrypted.
Set WIIFORM_FORCE_PULL=1 to always pull the container images used by the command.
EOF
}

die() {
	printf 'build.sh: %s\n' "$*" >&2
	exit 1
}

sops_() {
	sops --config "${root}/.sops.yml" "$@"
}

extract_seed() {
	# The seed is on stdout; don't copy its plaintext into Podman's logs.
	# shortcut: embedded keys only, add --keys if footerless backups are needed.
	podman run --rm --pull="${pull_policy}" --userns=keep-id --network=none --log-driver=none \
		-v "${backup}:/backup.bin:ro" ghcr.io/vic1707/wii-seed:main /backup.bin
}

wiiform() {
	podman run --rm -i --pull="${pull_policy}" --userns=keep-id --umask=0077 --log-driver=none \
		-v "${profile}:/work" ghcr.io/vic1707/wiiform:main \
		--seed - --recipe "/work/${recipe##*/}" --boot-policy preserve-source --output /work/out
}

case "${1:-}:$#" in
	-h:1 | --help:1)
		usage
		exit 0
		;;
	extract:3 | build:2) ;;
	build:4) [[ $3 == --from-backup ]] || die "expected --from-backup BACKUP" ;;
	*)
		usage >&2
		exit 2
		;;
esac

case "${WIIFORM_FORCE_PULL:-0}" in
	0) pull_policy=missing ;;
	1) pull_policy=always ;;
	*) die "WIIFORM_FORCE_PULL must be 0 or 1" ;;
esac

root=$(realpath -- "${BASH_SOURCE[0]}")
root=${root%/*}
[[ -d $2 ]] || die "profile directory not found: $2"
profile=$(realpath -- "$2")
seed="${profile}/seed.yml"
backup=
if [[ $1 == extract || $# == 4 ]]; then
	backup=${!#}
	[[ -f ${backup} && -r ${backup} ]] || die "backup not readable: ${backup}"
	backup=$(realpath -- "${backup}")
fi
umask 077

if [[ $1 == extract ]]; then
	[[ ! -e ${seed} && ! -L ${seed} ]] || die "refusing to replace ${seed}"
	tmp=$(mktemp -d "${profile}/.seed.XXXXXX")
	trap 'rm -f -- "${tmp}/seed.yml"; rmdir -- "${tmp}"' EXIT
	extract_seed | sops_ encrypt --filename-override "${seed}" > "${tmp}/seed.yml"
	[[ -s "${tmp}/seed.yml" ]] || die "SOPS did not produce an encrypted seed"
	# Publish only after both commands succeed, without replacing an existing seed.
	ln -- "${tmp}/seed.yml" "${profile}/"
	printf 'Saved %s\n' "${seed}"
	exit 0
fi

recipe="${profile}/recipe.yml"
[[ -f ${recipe} && -r ${recipe} ]] || die "recipe not readable: ${recipe}"
[[ ! -e "${profile}/out" && ! -L "${profile}/out" ]] || die "output already exists: ${profile}/out"
seed_status=
if [[ -z ${backup} ]]; then
	[[ -f ${seed} && -r ${seed} ]] || die "seed not readable: ${seed}"
	seed_status=$(sops_ filestatus "${seed}")
fi
if [[ -z ${SOPS_AGE_KEY_FILE:-} && -f "${root}/.wiis.age" ]]; then
	export SOPS_AGE_KEY_FILE="${root}/.wiis.age"
fi

encrypted='{"encrypted":true}'
recipe_status=$(sops_ filestatus "${recipe}")
if [[ ${recipe_status} == "${encrypted}" ]]; then
	# Keep the private copy beside recipe.yml so relative asset paths still resolve.
	tmp=$(mktemp "${profile}/.recipe.XXXXXX")
	trap 'rm -f -- "${tmp}"' EXIT
	trap 'exit 129' HUP
	trap 'exit 130' INT
	trap 'exit 143' TERM
	sops_ decrypt "${recipe}" > "${tmp}"
	[[ -s ${tmp} ]] || die "SOPS did not produce a decrypted recipe"
	recipe=${tmp}
fi

if [[ -n ${backup} ]]; then
	extract_seed | wiiform
elif [[ ${seed_status} == "${encrypted}" ]]; then
	sops_ decrypt "${seed}" | wiiform
else
	wiiform < "${seed}"
fi
