"""Exercise the build's actual curl policy against transient/permanent HTTP errors."""
from __future__ import annotations

import http.server
import shlex
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path

GUEST = Path(__file__).resolve().parents[1]


class PackageDownloadTests(unittest.TestCase):
    def transfer(self, statuses):
        requests = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append(time.monotonic())
                status = statuses[min(len(requests) - 1, len(statuses) - 1)]
                body = b'package contents' if status == 200 else b'error response'
                self.send_response(status)
                self.send_header('Content-Length', str(len(body)))
                if status == 429:
                    self.send_header('Retry-After', '1')
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        with http.server.HTTPServer(('127.0.0.1', 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with tempfile.TemporaryDirectory() as temporary:
                    output = Path(temporary) / 'package.part'
                    policy = next(line.split('=', 1)[1].strip() for line in
                                  (GUEST / 'pacman-download.conf').read_text().splitlines()
                                  if line.startswith('XferCommand ='))
                    url = f'http://127.0.0.1:{server.server_port}/package'
                    command = [str(output) if arg == '%o' else url if arg == '%u' else arg
                               for arg in shlex.split(policy)]
                    result = subprocess.run(command, capture_output=True, timeout=10)
                    data = output.read_bytes() if output.exists() else b''
            finally:
                server.shutdown()
                thread.join(timeout=2)
        return result, data, requests

    def test_rate_limit_retries_after_requested_delay(self):
        result, data, requests = self.transfer([429, 200])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(data, b'package contents')
        self.assertEqual(len(requests), 2)
        self.assertGreaterEqual(requests[1] - requests[0], 0.95)

    def test_missing_package_fails_without_retry(self):
        result, data, requests = self.transfer([404])
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(len(requests), 1)
        self.assertEqual(data, b'')

    def test_policy_is_build_only_and_used_at_each_stage(self):
        container = (GUEST / 'Containerfile').read_text()
        self.assertIn('COPY guest/pacman-download.conf /etc/pacman.d/build-download.conf', container)
        self.assertIn('Include = /etc/pacman.d/build-download.conf', container)
        self.assertIn('cp /etc/pacman.d/build-download.conf /rootfs/etc/pacman.d/build-download.conf', container)
        for path in ['build.sh', 'scripts/refresh-package-lock.sh']:
            self.assertIn('$guest_dir/pacman-download.conf', (GUEST / path).read_text())
        self.assertNotIn('XferCommand', (GUEST / 'pacman.aarch64.conf').read_text())
        self.assertNotIn('build-download.conf', (GUEST / 'pacman.aarch64.conf').read_text())

    def test_generated_build_configs_allow_writing_root_owned_downloads(self):
        # Execute the actual config-generation fragments without running a build.
        build = (GUEST / 'build.sh').read_text()
        start = build.index('options_sections=0\n')
        end = build.index('(( options_sections == 1 ))', start)
        refresh = (GUEST / 'scripts/refresh-package-lock.sh').read_text()
        refresh_command = next(line for line in refresh.splitlines()
                               if line.startswith('sed -e '))
        with tempfile.TemporaryDirectory() as temporary:
            for fragment in [build[start:end], refresh_command]:
                config = Path(temporary) / 'pacman.conf'
                prelude = '\n'.join([
                    'set -euo pipefail',
                    'guest_dir=' + shlex.quote(str(GUEST)),
                    'upstream_pacman_config=' + shlex.quote(str(GUEST / 'pacman.aarch64.conf')),
                    'pacman_config=' + shlex.quote(str(config)),
                    'config=' + shlex.quote(str(config)),
                    'package_cache=' + shlex.quote(temporary),
                    'pinned_repo=""',
                ])
                subprocess.run(['bash', '-c', prelude + '\n' + fragment], check=True)
                lines = config.read_text().splitlines()
                self.assertFalse(any(line.startswith('DownloadUser') for line in lines))
                self.assertEqual([line for line in lines if line.startswith('ParallelDownloads')],
                                 ['ParallelDownloads = 1'])
                self.assertTrue(any(line.startswith('XferCommand =') for line in lines))
                self.assertIn('SigLevel = Required DatabaseOptional', lines)
        self.assertIn('DownloadUser = alpm', (GUEST / 'pacman.aarch64.conf').read_text())
