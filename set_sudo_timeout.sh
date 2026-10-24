#!/usr/bin/env bash
# Set a three-hour sudo password cache for daniil (or the supplied user).
set -euo pipefail

if (( EUID != 0 )); then
    exec sudo bash "$0" "$@"
fi

target_user="${1:-daniil}"
if [[ ! "$target_user" =~ ^[a-z_][a-z0-9_-]*\$?$ ]]; then
    echo "Invalid user name: $target_user" >&2
    exit 1
fi
id "$target_user" >/dev/null
command -v visudo >/dev/null
visudo -c

destination="/etc/sudoers.d/zz-timeout-${target_user}"
temporary="$(mktemp)"
trap 'rm -f -- "$temporary"' EXIT
printf 'Defaults:%s timestamp_timeout=180\n' "$target_user" > "$temporary"
visudo -cf "$temporary"
install -o root -g root -m 0440 "$temporary" "$destination"
visudo -c
printf 'Sudo password timeout for %s is now 180 minutes.\n' "$target_user"
