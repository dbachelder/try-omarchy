from pathlib import Path
import importlib.util
import tempfile
import unittest

GUEST = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('upgrade_pinch', GUEST / 'scripts/upgrade-pinch-input.py')
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)
SETTINGS = (GUEST / 'native-overlay/usr/share/try-omarchy/pinch-input.lua').read_bytes()


class PinchMigrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'input.lua'
        self.original = b'-- personal overrides\nhl.config({input = {sensitivity = 0.2}})'
        self.path.write_bytes(self.original)
        self.path.chmod(0o600)

    def test_preserves_settings_and_backups_and_is_idempotent(self):
        backup = migration.upgrade(self.path, SETTINGS, lambda command: '')
        self.assertEqual(backup.read_bytes(), self.original)
        applied = self.path.read_bytes()
        self.assertTrue(applied.startswith(self.original))
        self.assertIn(SETTINGS.rstrip(), applied)
        self.assertNotIn(b'dofile', applied)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertIsNone(migration.upgrade(self.path, SETTINGS, lambda command: ''))
        self.assertEqual(self.path.read_bytes(), applied)
        self.assertEqual(len(list(self.path.parent.glob('*.bak'))), 1)

    def test_validation_error_restores_exact_original(self):
        calls = []
        def run(command):
            calls.append(command)
            return 'Lua error' if calls == ['configerrors', 'reload', 'configerrors'] else ''
        with self.assertRaisesRegex(RuntimeError, 'original configuration restored'):
            migration.upgrade(self.path, SETTINGS, run)
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(calls[-1], 'reload')

    def test_preexisting_error_does_not_change_anything(self):
        with self.assertRaisesRegex(RuntimeError, 'configuration errors'):
            migration.upgrade(self.path, SETTINGS, lambda command: 'Existing Lua error')
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(list(self.path.parent.glob('*.bak')), [])

    def test_user_edits_to_managed_block_are_preserved(self):
        migration.upgrade(self.path, SETTINGS, lambda command: '')
        modified = self.path.read_bytes().replace(b'tap_to_click = false', b'tap_to_click = true')
        self.path.write_bytes(modified)
        with self.assertRaisesRegex(RuntimeError, 'has been edited'):
            migration.upgrade(self.path, SETTINGS, lambda command: '')
        self.assertEqual(self.path.read_bytes(), modified)

    def test_symlink_is_not_replaced(self):
        alias = self.path.parent / 'alias.lua'
        alias.symlink_to(self.path)
        with self.assertRaisesRegex(RuntimeError, 'non-symlinked'):
            migration.upgrade(alias, SETTINGS, lambda command: '')
        self.assertTrue(alias.is_symlink())
        self.assertEqual(self.path.read_bytes(), self.original)
