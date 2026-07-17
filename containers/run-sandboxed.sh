#!/usr/bin/env bash
# run-sandboxed.sh — запустить движок AI Ops в ИЗОЛИРОВАННОМ контейнере (P0.2 runtime jail).
#
# Что enforce'ит контейнер (чего брокер в процессе НЕ может):
#   --read-only            root-fs только для чтения; писать некуда, кроме bind'а и tmpfs
#   bind <child> -> /work   ЕДИНСТВЕННАЯ writable точка (worktree ребёнка); хост не тронут
#   --tmpfs /tmp,/home     writable временные каталоги (npm/pip кэш) без записи на root-fs
#   --memory/--cpus/--pids-limit   лимиты ресурсов (модель/сборка не съедят машину)
#   --cap-drop=ALL + --security-opt=no-new-privileges   без привилегий/эскалации
#   --user 10001 (non-root, зашит в образ)
#
# ЧЕСТНО: сеть НЕ отключена — движку нужен egress к API модели и реестрам (npm/pip). Для жёсткого
# контроля подставьте свой egress-allowlist прокси (см. docs/container-isolation.md) или задайте
# AI_OPS_NETWORK=none, если модель/зависимости уже локальны.
#
# Использование:
#   containers/run-sandboxed.sh <child_repo> "<task>" [доп. флаги ai-ops run]
# Пример:
#   OPENAI_COMPATIBLE_BASE_URL=... OPENAI_COMPATIBLE_API_KEY=... \
#     containers/run-sandboxed.sh ~/ii-sreda "почини тест даты" \
#       --engine pipeline --provider openai-compatible --model deepseek-chat \
#       --execute --sandbox --baseline-diff
set -euo pipefail

CHILD="${1:?укажи путь к child-репозиторию}"; shift
TASK="${1:?укажи текст задачи}"; shift
IMAGE="${AI_OPS_IMAGE:-ai-ops-engine:latest}"
MEM="${AI_OPS_MEM:-2g}"
CPUS="${AI_OPS_CPUS:-2}"
NET="${AI_OPS_NETWORK:-bridge}"   # bridge (нужен egress к модели/реестрам) | none (всё локально)

CHILD_ABS="$(cd "$CHILD" && pwd)"

# Пробрасываем ТОЛЬКО имена секрет-переменных (значения берутся из окружения, не в образ).
ENVFLAGS=()
for v in OPENAI_COMPATIBLE_BASE_URL OPENAI_COMPATIBLE_API_KEY ANTHROPIC_API_KEY \
         OPENAI_API_KEY GITHUB_TOKEN GH_TOKEN; do
  [ -n "${!v:-}" ] && ENVFLAGS+=(-e "$v")
done

exec docker run --rm \
  --read-only \
  --network "$NET" \
  --mount "type=bind,src=${CHILD_ABS},dst=/work" \
  --tmpfs /tmp:rw,size=1g \
  --tmpfs /home/runner:rw,size=1g \
  --workdir /work \
  --memory "$MEM" --cpus "$CPUS" --pids-limit 512 \
  --cap-drop ALL --security-opt no-new-privileges \
  "${ENVFLAGS[@]}" \
  "$IMAGE" \
  run "$TASK" /work "$@"
