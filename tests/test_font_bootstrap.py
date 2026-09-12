"""No-clobber, no-network local restoration from the user-owned original ZIP."""
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import install_original_fonts as installer

class FontBootstrapTests(unittest.TestCase):
    def test_wrong_archive_rejected_without_creating_destination(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);source=root/'wrong.zip';source.write_bytes(b'not the original ZIP')
            target=root/'fonts'
            with self.assertRaises(ValueError):installer.install(source,target)
            self.assertFalse(target.exists())
    def test_restored_fonts_match_original_payload_hashes(self):
        target=Path(__file__).resolve().parents[1]/'resources/fonts'
        for name,digest in installer.FONT_SHA256.items():
            self.assertTrue((target/name).is_file(),'Run install_original_fonts.py first')
            self.assertEqual(installer.digest_file(target/name),digest)
