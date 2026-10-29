#!/usr/bin/env bash
# Только Git inventory и запуск закреплённых CLI. Проверяемые скрипты не исполняются.
set -euo pipefail

mode=all
base=
case "${1:-}" in
  '') [[ $# -eq 0 ]] || exit 2 ;;
  --inventory)
    [[ $# -eq 1 ]] || exit 2
    mode=inventory
    ;;
  --changed)
    [[ $# -eq 2 ]] || exit 2
    mode=changed
    base=$2
    ;;
  *)
    echo 'Usage: check-shell-quality.sh [--inventory | --changed BASE]' >&2
    exit 2
    ;;
esac
root=$(git rev-parse --show-toplevel) || exit 2
cd "$root" || exit 2
inventory=$(mktemp) || exit 2
trap 'rm -f "$inventory"' EXIT
trap 'exit 2' HUP INT TERM
# Не process substitution: ошибка Git обязана дойти до вызывающего.
if [[ $mode == changed ]]; then
  git rev-parse --verify --end-of-options "$base^{commit}" >/dev/null || exit 2
  git diff --name-only --no-renames --diff-filter=ACMR -z "$base" -- '*.sh' >"$inventory" || exit 2
else
  git ls-files -z -- '*.sh' >"$inventory" || exit 2
fi
if [[ $mode != inventory ]]; then
  if ! command -v shellcheck >/dev/null || ! command -v shfmt >/dev/null; then
    echo 'INCOMPLETE: нужны ShellCheck 0.11.0 и shfmt v3.14.1 в PATH' >&2
    exit 2
  fi
  shellcheck_version=$(shellcheck --version) || exit 2
  shfmt_version=$(shfmt --version) || exit 2
  if ! printf '%s\n' "$shellcheck_version" | grep -Fxq 'version: 0.11.0' || [[ $shfmt_version != v3.14.1 ]]; then
    echo 'INCOMPLETE: версии CLI отличаются от ShellCheck 0.11.0 / shfmt v3.14.1' >&2
    exit 2
  fi
fi

checked=0
result=0
while IFS= read -r -d '' file; do
  first=
  if [[ ! -f $file ]] || [[ -L $file ]]; then
    printf 'INCOMPLETE: не обычный файл: %s\n' "$file" >&2
    result=2
    continue
  fi
  IFS= read -r first <"$file" || true
  case "$first" in
    '#!/bin/bash' | '#!/usr/bin/bash' | '#!/usr/bin/env bash')
      dialect=bash
      sc_dialect=bash
      ;;
    '#!/bin/sh' | '#!/usr/bin/sh' | '#!/usr/bin/env sh')
      dialect=posix
      sc_dialect='sh'
      ;;
    *)
      printf 'INCOMPLETE: неизвестный shebang: %s\n' "$file" >&2
      result=2
      continue
      ;;
  esac
  if [[ $mode == inventory ]]; then
    printf '%s\t%s\n' "$dialect" "$file"
    continue
  fi
  checked=$((checked + 1))
  printf '\nCHECK %s (%s)\n' "$file" "$dialect"
  if shellcheck --norc --format=gcc --shell="$sc_dialect" "./$file"; then
    :
  else
    rc=$?
    if [[ $rc -gt 1 ]]; then result=2; elif [[ $result -eq 0 ]]; then result=1; fi
  fi
  if shfmt -ln "$dialect" -i 2 -ci -bn -d "./$file"; then
    :
  else
    rc=$?
    if [[ $rc -gt 1 ]]; then result=2; elif [[ $result -eq 0 ]]; then result=1; fi
  fi
done <"$inventory"
printf '\nSHELL_QUALITY mode=%s checked=%s result=%s (0=clean, 1=findings, 2=incomplete)\n' "$mode" "$checked" "$result"
exit "$result"
