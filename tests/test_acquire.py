import tempfile
import unittest
import io
import json
from unittest.mock import patch
from pathlib import Path
from eval_audit.acquire import destination, selected_paths, load_inventory


class AcquireTests(unittest.TestCase):
    def test_inventory_bootstrap_pins_and_caches_revision(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch('eval_audit.acquire.urlopen', return_value=io.BytesIO(b'{"sha":"rev","siblings":[]}')) as request:
                self.assertEqual(load_inventory(Path(directory),'org/data','rev')['sha'],'rev')
            self.assertIn('/revision/rev',request.call_args.args[0])
            with patch('eval_audit.acquire.urlopen', side_effect=AssertionError('unexpected network')):
                self.assertEqual(load_inventory(Path(directory),'org/data','rev')['siblings'],[])
            with self.assertRaises(ValueError):
                load_inventory(Path(directory),'org/data','different')

    def test_selection_excludes_other_tasks_and_workspace(self):
        paths = ["general/envs/a/verify.py", "general/envs/a/system/x/state.db",
                 "general/envs/a/workspace/file.json", "general/envs/ab/verify.py",
                 "general/envs/b/instruction.md", "general/envs/a/asset.zip"]
        self.assertEqual(selected_paths(paths, ["a"]),
                         ["general/envs/a/system/x/state.db", "general/envs/a/verify.py"])

    def test_empty_selection_is_empty(self):
        self.assertEqual(selected_paths(["general/envs/a/verify.py"], []), [])

    def test_destination_rejects_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for path in ["../other", "/absolute", "x/../../other", "x\\..\\other", ""]:
                with self.subTest(path=path), self.assertRaises(ValueError):
                    destination(root, path)
            self.assertEqual(destination(root, "a/b.json"), root.resolve() / "a/b.json")

    def test_destination_rejects_symlink_escape(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as other:
            root = Path(directory)
            (root / "outside").symlink_to(other, target_is_directory=True)
            with self.assertRaises(ValueError):
                destination(root, "outside/file")
