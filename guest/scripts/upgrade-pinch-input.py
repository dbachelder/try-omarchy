#!/usr/bin/env python3
"""Apply the pinch input override to an existing user's Lua configuration."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import stat
import subprocess
import tempfile

BEGIN = b'-- BEGIN Try Omarchy pinch migration v1\n'
END = b'-- END Try Omarchy pinch migration v1\n'


def hyprctl(command: str) -> str:
    result = subprocess.run(['hyprctl', command], capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or f'hyprctl {command} failed')
    return result.stdout.strip()


def check_config(run) -> None:
    errors = run('configerrors')
    if errors:
        raise RuntimeError(f'Hyprland reports configuration errors:\n{errors}')


def replace_file(path: Path, data: bytes, mode: int) -> None:
    fd, temporary = tempfile.mkstemp(prefix='.pinch-input.', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as output:
            os.fchmod(output.fileno(), mode)
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def upgrade(path: Path, settings: bytes, run=hyprctl) -> Path | None:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f'Expected a regular, non-symlinked configuration file: {path}')
    info = path.stat()
    if info.st_uid != os.getuid():
        raise RuntimeError('Run this command as the user who owns input.lua, without sudo')
    original = path.read_bytes()
    block = BEGIN + settings.rstrip() + b'\n' + END
    check_config(run)
    if BEGIN in original or END in original:
        if original.count(BEGIN) != 1 or original.count(END) != 1 or block not in original:
            raise RuntimeError('The managed pinch block has been edited; review it before migrating')
        run('reload')
        check_config(run)
        return None

    # Keep an exact backup; the managed block does not depend on files that are
    # absent from older factory images, or on the shared checkout after migration.
    mode = stat.S_IMODE(info.st_mode)
    fd, backup_name = tempfile.mkstemp(prefix='input.lua.before-pinch.', suffix='.bak', dir=path.parent)
    backup = Path(backup_name)
    with os.fdopen(fd, 'wb') as output:
        os.fchmod(output.fileno(), mode)
        output.write(original)
    updated = original + (b'' if original.endswith(b'\n') else b'\n') + b'\n' + block
    if path.read_bytes() != original:
        raise RuntimeError('input.lua changed during migration; no configuration was written')
    replace_file(path, updated, mode)
    try:
        run('reload')
        check_config(run)
    except Exception as error:
        if path.read_bytes() != updated:
            raise RuntimeError(f'Validation failed and input.lua was edited concurrently; restore from {backup}') from error
        replace_file(path, original, mode)
        try:
            run('reload')
        except Exception as rollback_error:
            raise RuntimeError(f'Original file restored, but reload failed: {rollback_error}; backup: {backup}') from error
        raise RuntimeError(f'Validation failed; original configuration restored: {error}') from error
    return backup


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=Path.home() / '.config/hypr/input.lua')
    args = parser.parse_args()
    if os.getuid() == 0:
        parser.error('Run inside the guest desktop as your normal user, without sudo')
    settings = Path(__file__).resolve().parents[1] / 'native-overlay/usr/share/try-omarchy/pinch-input.lua'
    try:
        backup = upgrade(args.config, settings.read_bytes())
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        parser.exit(1, f'pinch migration: {error}\n')
    print('Pinch settings applied; Hyprland configuration is valid.' if backup else
          'Pinch settings already applied; Hyprland configuration is valid.')
    if backup:
        print(f'Backup: {backup}')
    print('Use the rebuilt Mac app with this saved VM to receive pinch gestures.')


if __name__ == '__main__':
    main()
