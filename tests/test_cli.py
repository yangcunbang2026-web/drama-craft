"""Behavioral tests for packaging, isolation and non-overwriting operations. MIT."""
import contextlib
import hashlib
import importlib.util
import io
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('drama_craft', ROOT / 'scripts/drama_craft.py')
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)


class PublicPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='drama-craft-test-')
        self.base = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def copy_public(self):
        root = self.base / 'repo'
        for name in cli.PUBLIC_FILES:
            dest = root / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / name, dest)
        return root

    def test_repository_validates(self):
        self.assertEqual(cli.validate()['prompts'], 27)

    def test_broken_link_is_rejected(self):
        root = self.copy_public()
        with (root / 'README.md').open('a', encoding='utf-8') as handle:
            handle.write('\n[bad](missing-document.md)\n')
        with self.assertRaisesRegex(cli.ValidationError, 'broken'):
            cli.validate(root)

    def test_personal_path_and_unexpected_file_rejected(self):
        root = self.copy_public()
        with (root / 'README.md').open('a', encoding='utf-8') as handle:
            handle.write('\n' + chr(67) + ':' + chr(92) + 'personal' + chr(92) + 'note.md\n')
        with self.assertRaisesRegex(cli.ValidationError, 'absolute Windows'):
            cli.validate(root)
        (root / 'private-note.md').write_text('private', encoding='utf-8')
        with self.assertRaisesRegex(cli.ValidationError, 'Unexpected'):
            cli.validate(root)

    def test_initialize_does_not_overwrite(self):
        dest = self.base / 'project'
        cli.initialize(dest, 'A receipt does not match a sealed parcel.')
        original = (dest / 'PROJECT.md').read_bytes()
        self.assertIn('A receipt', original.decode('utf-8'))
        with self.assertRaises(FileExistsError):
            cli.initialize(dest, 'different')
        self.assertEqual(original, (dest / 'PROJECT.md').read_bytes())

    def test_install_is_portable_and_keeps_attribution(self):
        dest = self.base / 'installed-skill'
        cli.install(dest)
        actual = {p.relative_to(dest).as_posix() for p in dest.rglob('*') if p.is_file()}
        self.assertEqual(actual, set(cli.BUNDLE_FILES))
        self.assertIn('Serge Shima', cli.read(dest / 'references/ATTRIBUTION.md'))
        with self.assertRaises(FileExistsError):
            cli.install(dest)

    def test_package_deterministic_and_excludes_private_projects(self):
        first, second = self.base / 'first.zip', self.base / 'second.zip'
        cli.pack(first)
        cli.pack(second)
        self.assertEqual(hashlib.sha256(first.read_bytes()).digest(),
                         hashlib.sha256(second.read_bytes()).digest())
        with zipfile.ZipFile(first) as bundle:
            self.assertEqual(set(bundle.namelist()), {'drama-craft/' + n for n in cli.BUNDLE_FILES})
            self.assertFalse(any('PROJECT.md' in n or '.git/' in n for n in bundle.namelist()))
        with self.assertRaises(FileExistsError):
            cli.pack(first)

    def test_prompt_roundtrip_with_context_and_unknown_id(self):
        context = self.base / 'context.md'
        context.write_text('Approved scope: one scene; no generation.', encoding='utf-8')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = cli.main(['prompt', 'T10', '--context', str(context)])
        self.assertEqual(status, 0)
        self.assertIn(cli.prompt_catalog()['T10'][1], output.getvalue())
        self.assertIn('Approved scope', output.getvalue())
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(['prompt', 'T99']), 1)

    def test_zip_normalizes_text_bom_and_line_endings(self):
        root = self.copy_public()
        path = root / 'SKILL.md'
        canonical = cli.read(path)
        path.write_bytes(b'\xef\xbb\xbf' + canonical.replace('\n', '\r\n').encode('utf-8'))
        archive = self.base / 'normalized.zip'
        cli.pack(archive, root)
        with zipfile.ZipFile(archive) as bundle:
            self.assertEqual(bundle.read('drama-craft/SKILL.md'), canonical.encode('utf-8'))

    def test_missing_attribution_is_rejected(self):
        root = self.copy_public()
        (root / 'references/ATTRIBUTION.md').write_text('No credits.', encoding='utf-8')
        with self.assertRaisesRegex(cli.ValidationError, 'attribution'):
            cli.validate(root)


if __name__ == '__main__':
    unittest.main()
