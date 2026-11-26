"""Условное повторное чтение страниц GitHub Actions внутри одного сбора плана выпуска."""
import json
import os
import re
import subprocess
from urllib.parse import urlencode

from ai_ops_kit.integrations.github import GitHubClient, GitHubError


# Лимиты касаются сохранённых ответов. Большую страницу читаем как обычно без запоминания.
_MAX_PAGES = 256
_MAX_BODY = 512 * 1024
_MAX_TOTAL = 16 * 1024 * 1024


def capture_reader(client):
    """Только штатный GH_TOKEN + gh на github.com; прочие клиенты сохраняют свой транспорт."""
    if (type(client) is GitHubClient and os.environ.get("GH_TOKEN")
            and os.environ.get("GH_HOST", "github.com") == "github.com"
            and client.availability().transport == "gh"):
        return _CapturePages(client)
    return client


class _CapturePages:
    def __init__(self, client):
        self.repo = client.repo
        self.closing_issue_numbers = client.closing_issue_numbers
        self.client = client
        self.pages = {}
        self.bytes_held = 0
        self._token = os.environ["GH_TOKEN"]

    def remember(self, endpoint, tag, body):
        if (len(self.pages) < _MAX_PAGES and len(body) <= _MAX_BODY
                and self.bytes_held + len(body) <= _MAX_TOTAL):
            self.pages[endpoint] = (tag, body)
            self.bytes_held += len(body)

    def read_page(self, path, params=None):
        prefix = f"repos/{self.repo}/actions/workflows/"
        if not (path.startswith(prefix) and re.fullmatch(r"[a-z0-9_-]+\.yml/runs", path[len(prefix):])
                and params and params.get("event") == "pull_request"):
            return self.client.read_page(path, params)
        endpoint = path + "?" + urlencode(sorted(params.items()))
        if os.environ.get("GH_TOKEN") != self._token or os.environ.get("GH_HOST", "github.com") != "github.com":
            raise GitHubError("workflow page credential context changed")
        previous = self.pages.pop(endpoint, None)
        if previous:
            self.bytes_held -= len(previous[1])
        cmd = ["gh", "api", "--include", "--hostname", "github.com", "-H", "Accept: application/vnd.github+json"]
        if previous is not None:
            cmd += ["-H", "If-None-Match: " + previous[0]]
        try:
            proc = subprocess.run([*cmd, endpoint], capture_output=True, timeout=self.client.timeout * 4)
        except (OSError, subprocess.SubprocessError) as exc:
            raise GitHubError("workflow page unavailable") from exc
        # gh выводит status line с LF, поля с CRLF, затем пустую строку.
        parts = re.split(rb"\r?\n\r?\n", proc.stdout, maxsplit=1)
        headers = parts[0].splitlines()
        status = re.fullmatch(rb"HTTP/[0-9.]+ ([0-9]{3})(?: [^\r\n]*)?", headers[0]) if headers else None
        if len(parts) != 2 or not status:
            raise GitHubError("invalid workflow page response")
        tags = []
        cache_allowed = True
        for line in headers[1:]:
            key, _, value = line.partition(b":")
            if key.lower() == b"etag":
                tags.append(value.strip())
            if ((key.lower() == b"cache-control" and b"no-store" in value.lower())
                    or (key.lower() == b"vary" and b"*" in value)):
                cache_allowed = False
        code = int(status[1])
        if code == 304:
            # gh api печатает подтверждённый HTTP 304 и завершает его с кодом 1.
            if (previous is None or parts[1] or (tags and tags != [previous[0].encode("ascii")]) or
                    not (proc.returncode == 0 or (proc.returncode == 1 and proc.stderr.strip() == b"gh: HTTP 304"))):
                raise GitHubError("invalid conditional workflow response")
            if cache_allowed:
                self.remember(endpoint, *previous)
            return json.loads(previous[1])
        if code != 200 or proc.returncode:
            raise GitHubError(f"workflow page HTTP {code}")
        data = json.loads(parts[1])
        if cache_allowed and len(tags) == 1 and len(tags[0]) <= 1024 and re.fullmatch(rb'(?:W/)?"[\x21\x23-\x7e]*"', tags[0]):
            self.remember(endpoint, tags[0].decode("ascii"), parts[1])
        return data
