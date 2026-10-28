"""Сборка ai-ops-kit. Конфигурация — в pyproject.toml; здесь только точка входа setuptools.

ЧЕГО ЗДЕСЬ БОЛЬШЕ НЕТ (v3.33.1). Прежде setup.py на уровне модуля писал `.pth` в site-packages
ПОЛЬЗОВАТЕЛЯ, подкладывая корень репозитория, `tools/` и `validation/` в sys.path КАЖДОГО процесса
Python на машине. Три беды сразу:

  1. Файл писался при любом запуске setup.py — включая сборку колеса в изолированном окружении и
     установку в venv, — но попадал в общий пользовательский site, за пределы целевого окружения.
  2. Путь зашивался абсолютный, от каталога сборки. У пользователя, ставящего пакет из sdist, это
     временный каталог, который тут же удаляется: в системе оставался мусорный .pth.
  3. Главное: это и есть тот самый пояс, который прячет дефекты. Весь август репозиторий чинил
     класс «работает локально из-за editable-установки» — а ставил себе эту установку сам, на любом
     `pip install`. Пакет, который правит sys.path чужих процессов, лишает и себя, и пользователя
     возможности увидеть, что он на самом деле сломан.

Корень данных определяется по VERSION. Для wheel ресурсы копируются под ai_ops_kit только
в каталоге сборки; checkout и editable продолжают читать единственный исходный экземпляр.
"""
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py
from setuptools.errors import FileError


RUNTIME_DATA_DIRS = (
    "registry", "quality", "workflows", "schemas", "decisions", "packages", "manifest",
    "standards", "knowledge", "planning", "templates", "context", "agents", "rules",
)


class BuildPyWithRuntimeData(build_py):
    """Одна декларация ресурсов для sdist и wheel, без переноса исходных каталогов."""

    def _runtime_sources(self):
        sources = [Path("VERSION")]
        for name in RUNTIME_DATA_DIRS:
            directory = Path(name)
            if not directory.is_dir():
                raise FileError(f"missing runtime data directory: {name}")
            sources.extend(p for p in sorted(directory.rglob("*"))
                           if p.is_file() and "__pycache__" not in p.parts
                           and p.suffix not in {".pyc", ".pyo"})
        for source in sources:
            if not source.is_file():
                raise FileError(f"missing runtime data file: {source}")
            if (Path("ai_ops_kit") / source).exists():
                raise FileError(f"runtime data collides with package source: {source}")
        return [str(p) for p in sources]

    def _runtime_mapping(self):
        return {str(Path(self.build_lib) / "ai_ops_kit" / p): p
                for p in self._runtime_sources()}

    def get_source_files(self):
        # egg_info/sdist вызывают этот публичный hook: архив содержит те же входы сборки.
        return super().get_source_files() + self._runtime_sources()

    def get_output_mapping(self):
        return {**super().get_output_mapping(), **self._runtime_mapping()}

    def get_outputs(self, include_bytecode=True):
        return sorted(set(super().get_outputs(include_bytecode)) | self._runtime_mapping().keys())

    def run(self):
        mapping = self._runtime_mapping()  # Отказ до копирования при неполных/конфликтных входах.
        super().run()
        if self.editable_mode:
            return
        for destination, source in mapping.items():
            self.mkpath(str(Path(destination).parent))
            self.copy_file(source, destination)

setup(cmdclass={"build_py": BuildPyWithRuntimeData})
