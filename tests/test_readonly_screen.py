"""Contract tests use inert temporary source fixtures, never corpus execution."""

import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import eval_audit.readonly_screen as readonly_screen
from eval_audit.readonly_screen import main, screen_environment


class ReadonlyScreenTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = self.root / "task_one"
        (self.env / "tools").mkdir(parents=True)
        self.verify_source = "def verify():\n    return {}\n"
        self.dispatcher_source = "def public_functions(module):\n    return []\n"
        self.write("verify.py", self.verify_source)
        self.write("mcp_http.py", self.dispatcher_source)
        self.write("manifest.json", {"mcp_servers": [{"name": "db"}]})
        self.write("verifier_meta.json", {
            "act": "none",
            "items": [{"id": "answer", "method": "llm", "files": ["answer.md"]}],
        })
        self.write("instruction.md", "Please do not modify any system records.\n")
        self.write("tools/db.py", "def inspect():\n    return None\n")

    def write(self, relative, value):
        path = self.env / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(value, str):
            path.write_text(value, encoding="utf-8")
        else:
            path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")

    def known_fixture_hashes(self):
        return {
            "verify.py": hashlib.sha256(self.verify_source.encode()).hexdigest(),
            "mcp_http.py": hashlib.sha256(self.dispatcher_source.encode()).hexdigest(),
        }

    def screen(self):
        return screen_environment(self.env, known_hashes=self.known_fixture_hashes())

    def test_direct_parameterized_insert_is_reported_with_function_and_lines(self):
        source = (
            "def publish(value):\n"
            "    con.execute(\"INSERT INTO records(value) VALUES (?)\", (value,))\n"
        )
        self.write("tools/db.py", source)
        result = self.screen()
        self.assertEqual("review_signal", result["status"])
        candidate = result["candidate"]
        self.assertTrue(candidate["review_signal"])
        self.assertEqual("task_one", candidate["task_id"])
        self.assertEqual("publish", candidate["tool_writes"][0]["tool_function"])
        self.assertEqual("INSERT INTO", candidate["tool_writes"][0]["operation"])
        self.assertEqual(2, candidate["tool_writes"][0]["literal_line"])
        self.assertEqual(2, candidate["tool_writes"][0]["execute_line"])
        self.assertEqual(["do not modify"], [x["phrase"] for x in candidate["instruction_evidence"]])
        self.assertFalse(candidate["manual_intent_review_required"])
        self.assertTrue(candidate["candidate_id"].startswith("readonly-"))

    def test_static_sql_assignment_flows_to_execute(self):
        self.write("tools/db.py", (
            "def publish(value):\n"
            "    sql = \"INSERT INTO records(value) VALUES (?)\"\n"
            "    con.execute(sql, (value,))\n"
        ))
        result = self.screen()
        self.assertEqual("review_signal", result["status"])
        write = result["candidate"]["tool_writes"][0]
        self.assertEqual(2, write["literal_line"])
        self.assertEqual(3, write["execute_line"])

    def test_update_delete_and_executemany_writes_are_recognized(self):
        cases = (
            ('con.execute("UPDATE records SET value = ?", (value,))', "UPDATE..SET"),
            ('con.execute("DELETE FROM records WHERE id = ?", (record_id,))', "DELETE FROM"),
            ('con.executemany("INSERT INTO records(value) VALUES (?)", values)', "INSERT INTO"),
        )
        for body, operation in cases:
            with self.subTest(operation=operation):
                self.write("tools/db.py", f"def mutate(value):\n    {body}\n")
                result = self.screen()
                self.assertEqual("review_signal", result["status"])
                self.assertEqual(operation, result["candidate"]["tool_writes"][0]["operation"])

    def test_comments_docstrings_and_select_queries_do_not_signal(self):
        self.write("tools/db.py", (
            '"""con.execute(\\\"INSERT INTO fake VALUES (1)\\\")"""\n'
            "# con.execute('DELETE FROM fake')\n"
            "def inspect():\n"
            '    """INSERT INTO still_fake VALUES (1)"""\n'
            '    con.execute("SELECT * FROM records")\n'
        ))
        result = self.screen()
        self.assertEqual("no_write_found", result["status"])
        self.assertNotIn("candidate", result)

    def test_private_and_nested_functions_are_not_registered_tool_functions(self):
        self.write("tools/db.py", (
            "def _private():\n"
            '    con.execute("INSERT INTO records(value) VALUES (1)")\n'
            "def public():\n"
            "    def nested():\n"
            '        con.execute("DELETE FROM records")\n'
            "    return nested\n"
        ))
        self.assertEqual("no_write_found", self.screen()["status"])

    def test_rule_gate_or_src_protect_excludes_metadata(self):
        cases = (
            {"act": "none", "items": [{"id": "answer", "method": "rule", "files": ["answer.md"]}]},
            {"act": "none", "items": [{"id": "answer", "method": "llm", "files": ["answer.md"], "gate": True}]},
            {"act": "none", "items": [{"id": "answer", "method": "llm", "files": ["answer.md"]}], "src_protect": {}},
            {"act": "write", "items": [{"id": "answer", "method": "llm", "files": ["answer.md"]}]},
        )
        self.write("tools/db.py", 'def publish():\n    con.execute("INSERT INTO records VALUES (1)")\n')
        for metadata in cases:
            with self.subTest(metadata=metadata):
                self.write("verifier_meta.json", metadata)
                self.assertNotEqual("review_signal", self.screen()["status"])

    def test_noop_select_is_not_a_write_signal(self):
        self.write("tools/db.py", 'def inspect():\n    con.execute("SELECT * FROM records")\n')
        result = self.screen()
        self.assertEqual("no_write_found", result["status"])

    def test_dynamic_query_is_unknown_not_clean(self):
        self.write("tools/db.py", (
            "def publish(table, value):\n"
            '    sql = f"INSERT INTO {table}(value) VALUES (?)"\n'
            "    con.execute(sql, (value,))\n"
        ))
        result = self.screen()
        self.assertEqual("unknown_dynamic_sql", result["status"])
        self.assertFalse(result.get("candidate"))
        self.assertEqual("sql", result["unknown_dynamic_sql"][0]["query_expression"])

    def test_unknown_hash_is_skipped_and_test_override_is_explicit(self):
        self.write("tools/db.py", 'def publish():\n    con.execute("DELETE FROM records")\n')
        default = screen_environment(self.env)
        self.assertEqual("skipped_unknown_hash", default["status"])
        self.assertEqual({"verify.py", "mcp_http.py"}, set(default["hash_mismatches"]))
        overridden = self.screen()
        self.assertEqual("review_signal", overridden["status"])

    def test_manifest_must_expose_the_tool_module(self):
        self.write("tools/db.py", 'def publish():\n    con.execute("DELETE FROM records")\n')
        self.write("manifest.json", {"mcp_servers": [{"name": "other"}]})
        self.assertEqual("no_write_found", self.screen()["status"])

    def test_candidate_id_is_stable_and_cli_writes_json(self):
        self.write("tools/db.py", 'def publish():\n    con.execute("DELETE FROM records")\n')
        first = self.screen()["candidate"]["candidate_id"]
        second = self.screen()["candidate"]["candidate_id"]
        self.assertEqual(first, second)
        output = self.root / "report.json"
        with mock.patch.object(readonly_screen, "KNOWN_HASHES", self.known_fixture_hashes()):
            with contextlib.redirect_stdout(io.StringIO()):
                status = main(["--root", str(self.root), "--output", str(output)])
        self.assertEqual(0, status)
        report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual([first], report["candidate_ids"])
        self.assertEqual(1, report["candidate_count"])

    def test_unmatched_instruction_phrase_requires_manual_review(self):
        self.write("tools/db.py", 'def publish():\n    con.execute("DELETE FROM records")\n')
        self.write("instruction.md", "Review current records and report the result.\n")
        candidate = self.screen()["candidate"]
        self.assertEqual([], candidate["instruction_evidence"])
        self.assertTrue(candidate["manual_intent_review_required"])

    def test_source_is_parsed_but_never_executed(self):
        marker = self.root / "executed"
        source = f"from pathlib import Path\nPath({str(marker)!r}).touch()\n"
        self.write("tools/db.py", source)
        result = self.screen()
        self.assertEqual("no_write_found", result["status"])
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
