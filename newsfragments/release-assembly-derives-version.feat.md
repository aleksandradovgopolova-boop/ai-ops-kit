Осознанная сборка релиза теперь называет целевую версию: `release_assembly.assemble` по вехе или
расписанию выводит уровень бампа из состава newsfragments (feat → minor, иначе → patch) и печатает
`current → target` из VERSION, замыкая сборку без ручного угадывания X.Y.Z. Мажор сборка не выводит —
смена мажора остаётся осознанным решением владельца. Этим закрыт третий исход `kit-release-strategy`
(releases_are_assembled_by_milestone_or_schedule_not_reactively) — цель достигнута целиком.
