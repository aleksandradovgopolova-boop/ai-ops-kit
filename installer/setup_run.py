"""Локальный журнал и общий бюджет подпроцессов установки; без зависимостей движка."""
from __future__ import annotations

import json
import math
import os
import signal
import subprocess
import time
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

DEFAULT_TIMEOUT = 150.0


class SetupStopped(Exception):
    """Установка остановлена с сохранёнными доказательствами; это не успех."""


def positive_timeout(value):
    """Отвергнуть бесконечный, нулевой и отрицательный бюджет до записи файлов."""
    import argparse
    try:
        seconds = float(value)
    except (ValueError, TypeError):
        raise argparse.ArgumentTypeError('нужно положительное число секунд') from None
    if not math.isfinite(seconds) or seconds <= 0:
        raise argparse.ArgumentTypeError('нужно конечное положительное число секунд')
    return seconds


def _signal_group(process, sig):
    try:
        os.killpg(process.pid, sig)
    except ProcessLookupError:
        pass  # Группа уже завершилась между wait и сигналом.
    except PermissionError:
        # macOS может вернуть EPERM для группы, где остались только зомби.
        # Для ещё работающего собственного процесса отказ нельзя прятать.
        if process.poll() is None:
            raise


def _stop_process(process):
    """Сначала даём Git убрать свои lock-файлы; затем останавливаем оставшуюся группу."""
    if os.name == 'posix':
        _signal_group(process, signal.SIGTERM)
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            pass  # После ограниченной паузы ниже следует принудительная остановка.
        _signal_group(process, signal.SIGKILL)
    elif process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
    process.wait()



class SetupRun:
    """Новая попытка всегда пишет свой журнал; готовность прошлой попытки не наследуется."""

    def __init__(self, root: Path, *, timeout=DEFAULT_TIMEOUT):
        self.timeout = positive_timeout(timeout)
        self.root = root
        self.started = time.monotonic()
        self.run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ') + '-' + uuid4().hex[:8]
        self.directory = root / '.ai' / 'runtime' / 'setup' / self.run_id
        self.directory.mkdir(parents=True, exist_ok=False)
        # Работает и до init, и со старым блоком .gitignore уже установленной дочки.
        local_ignore = self.directory.parent / '.gitignore'
        if not local_ignore.exists():
            local_ignore.write_text('*\n', encoding='utf-8')
        self.journal = self.directory / 'events.jsonl'
        self.status = 'completed'
        self._previous_sigterm = None
        self.event('run_started', timeout_seconds=self.timeout,
                   human_active_minutes=None, USD=None, tokens=None)
        print(f'Журнал установки: {self.journal}', flush=True)
        print(f'Общий бюджет: {self.timeout:g} секунд. Повторный setup сохранит эту попытку.', flush=True)

    def event(self, event, **fields):
        row = {'schema_version': 1, 'run_id': self.run_id, 'event': event,
               'timestamp': datetime.now(timezone.utc).isoformat(),
               'run_elapsed_seconds': round(time.monotonic() - self.started, 6), **fields}
        with self.journal.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + '\n')
            stream.flush()
            os.fsync(stream.fileno())

    def remaining(self):
        return max(0.0, self.timeout - (time.monotonic() - self.started))

    def __enter__(self):
        if threading.current_thread() is threading.main_thread():
            self._previous_sigterm = signal.signal(signal.SIGTERM, self._interrupt)
        return self

    @staticmethod
    def _interrupt(signum, frame):
        raise KeyboardInterrupt

    def __exit__(self, kind, value, traceback):
        if self._previous_sigterm is not None:
            signal.signal(signal.SIGTERM, self._previous_sigterm)
        if kind is KeyboardInterrupt:
            self.status = 'interrupted'
        elif kind and self.status == 'completed':
            self.status = 'failed'
        self.event('run_finished', status=self.status)
        outcome = {'completed': 'завершена', 'failed': 'не завершена',
                   'timeout': 'превышено время ожидания', 'interrupted': 'прервана'}[self.status]
        print(f'Итог установки: {outcome}. Журнал: {self.journal}', flush=True)

    def command(self, step, command, *, env=None, accepted=(0,)):
        """Вывод направлен на диск ДО ожидания; timeout не уничтожает частичные данные."""
        budget = self.remaining()
        if budget <= 0:
            self.status = 'timeout'
            self.event('step_skipped', step=step, status='budget_exhausted')
            raise SetupStopped(f'Общий бюджет исчерпан перед шагом {step}.')
        stdout_path = self.directory / f'{step}.stdout.log'
        stderr_path = self.directory / f'{step}.stderr.log'
        started = time.monotonic()
        self.event('step_started', step=step, timeout_seconds=budget,
                   stdout_log=stdout_path.name, stderr_log=stderr_path.name)
        print(f'→ {step} (осталось {budget:.1f} с)', flush=True)
        status, code = 'failed', None
        try:
            with stdout_path.open('wb') as stdout, stderr_path.open('wb') as stderr:
                process = subprocess.Popen(command, cwd=self.root, env=env, stdout=stdout, stderr=stderr,
                                           start_new_session=os.name == 'posix')
                try:
                    code = process.wait(timeout=max(0.001, self.remaining()))
                    status = 'completed' if code in accepted else 'failed'
                except subprocess.TimeoutExpired:
                    status = self.status = 'timeout'
                    _stop_process(process)
                    code = process.returncode
                    raise SetupStopped(f'Шаг {step} остановлен: общий бюджет исчерпан.') from None
                except BaseException:
                    status = 'interrupted'
                    _stop_process(process)
                    code = process.returncode
                    raise
        except OSError as error:
            with stderr_path.open('a', encoding='utf-8') as stderr:
                stderr.write(f'\n{error}\n')
            if status in ('timeout', 'interrupted'):
                raise SetupStopped(f'Не удалось завершить процессы шага {step}: {error}') from error
            code = 1
        finally:
            if status != 'completed':
                self.status = status
            self.event('step_finished', step=step, status=status, exit_code=code,
                       elapsed_seconds=round(time.monotonic() - started, 6),
                       stdout_log=stdout_path.name, stderr_log=stderr_path.name)
        return subprocess.CompletedProcess(command, code,
                                           stdout_path.read_text(encoding='utf-8', errors='replace'),
                                           stderr_path.read_text(encoding='utf-8', errors='replace'))


def setup_cli(argv, setup):
    """Аддитивный флаг бюджета; ошибки аргументов не оставляют установку или журнал."""
    import argparse
    parser = argparse.ArgumentParser(prog='ai-ops setup')
    parser.add_argument('path')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--timeout-seconds', type=positive_timeout, default=DEFAULT_TIMEOUT,
                        help='общий бюджет подпроцессов установки (по умолчанию 150 секунд)')
    args = parser.parse_args(argv)
    return setup(args.path, apply=not args.dry_run, timeout=args.timeout_seconds)
