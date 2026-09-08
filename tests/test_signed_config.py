import shutil
import tempfile
import unittest
from pathlib import Path

from notion_proxy.signed_config import generate_keys, load_config, sign_config


class SignedConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.config = self.directory / "permissions.toml"
        self.config.write_bytes('[fetch]\nroot_path = ["홈", "test"]\n'.encode("utf-8"))
        generate_keys(self.directory, self.directory / ".private")
        sign_config(self.directory, self.directory / ".private")

    def test_copy_without_private_key_verifies(self):
        destination = self.directory / "copy"
        destination.mkdir()
        for name in ("permissions.toml", "permissions-public.pem", "permissions.sig"):
            shutil.copyfile(self.directory / name, destination / name)
        self.assertEqual(load_config(destination)["fetch"]["root_path"], ["홈", "test"])

    def test_config_edits_and_line_endings_require_new_signature(self):
        original = self.config.read_bytes()
        for changed in (original.replace(b"test", b"outside"), original + b"# comment\n", original.replace(b"\n", b"\r\n")):
            with self.subTest(changed=changed):
                self.config.write_bytes(changed)
                with self.assertRaises(PermissionError):
                    load_config(self.directory)
        sign_config(self.directory, self.directory / ".private")
        self.assertEqual(load_config(self.directory)["fetch"]["root_path"], ["홈", "test"])

    def test_missing_signature_or_public_key_fails(self):
        for name in ("permissions-public.pem", "permissions.sig"):
            path = self.directory / name
            content = path.read_bytes()
            path.unlink()
            with self.assertRaises(FileNotFoundError):
                load_config(self.directory)
            path.write_bytes(content)

    def test_different_signing_key_rejected(self):
        other = self.directory / "other"
        other.mkdir()
        generate_keys(other, other / ".private")
        shutil.copyfile(other / ".private" / "permissions-private.pem", self.directory / ".private" / "permissions-private.pem")
        with self.assertRaises(ValueError):
            sign_config(self.directory, self.directory / ".private")
        shutil.copyfile(other / "permissions-public.pem", self.directory / "permissions-public.pem")
        with self.assertRaises(PermissionError):
            load_config(self.directory)

    def test_key_generation_does_not_overwrite_keys(self):
        with self.assertRaises(FileExistsError):
            generate_keys(self.directory, self.directory / ".private")
        load_config(self.directory)
