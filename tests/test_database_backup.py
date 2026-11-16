import io
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from flask import Flask
from sqlalchemy.engine import URL

from app import database_backup
from app.extensions import db


class DatabaseBackupTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
        db.init_app(self.app)
        self.database_url = URL.create(
            "postgresql",
            username="bank_app",
            password="secret",
            host="db.example.test",
            port=5432,
            database="bank",
            query={"sslmode": "require"},
        )

    def test_create_backup_uses_public_schema_and_excludes_owner(self):
        captured_arguments = []

        def fake_run_tool(arguments, url, timeout=900):
            captured_arguments.extend(arguments)
            dump_path = Path(arguments[arguments.index("--file") + 1])
            dump_path.write_bytes(b"custom-format-dump")
            return SimpleNamespace(returncode=0)

        with self.app.app_context(), patch.object(
            database_backup, "_database_url", return_value=self.database_url
        ), patch.object(
            database_backup, "_utility_path", return_value="pg_dump"
        ), patch.object(
            database_backup, "_run_tool", side_effect=fake_run_tool
        ):
            temporary_directory, dump_path, filename = (
                database_backup.create_backup()
            )
            try:
                self.assertEqual(dump_path.read_bytes(), b"custom-format-dump")
                self.assertIn("--schema=public", captured_arguments)
                self.assertIn("--no-owner", captured_arguments)
                self.assertIn("--no-privileges", captured_arguments)
                self.assertTrue(filename.endswith(".dump"))
            finally:
                temporary_directory.cleanup()

    def test_tool_environment_uses_passfile_not_password_environment(self):
        environment, passfile = database_backup._tool_environment(
            self.database_url
        )
        try:
            self.assertNotIn("PGPASSWORD", environment)
            self.assertEqual(environment["PGSSLMODE"], "require")
            self.assertEqual(
                Path(environment["PGPASSFILE"]).read_text(encoding="utf-8"),
                "db.example.test:5432:bank:bank_app:secret\n",
            )
        finally:
            if passfile:
                passfile.unlink(missing_ok=True)

    def test_windows_utility_discovery_prefers_latest_installation(self):
        with tempfile.TemporaryDirectory() as program_files:
            for version in ("16", "18"):
                bin_directory = (
                    Path(program_files)
                    / "PostgreSQL"
                    / version
                    / "bin"
                )
                bin_directory.mkdir(parents=True)
                for utility in ("pg_dump", "pg_restore", "psql"):
                    (bin_directory / f"{utility}.exe").touch()

            with patch.dict(
                os.environ,
                {"ProgramFiles": program_files, "ProgramFiles(x86)": ""},
            ):
                utility = database_backup._windows_utility_path("pg_dump")

            self.assertEqual(
                Path(utility),
                Path(program_files)
                / "PostgreSQL"
                / "18"
                / "bin"
                / "pg_dump.exe",
            )

    def test_restore_is_scoped_and_runs_in_a_single_transaction(self):
        calls = []

        def fake_run_tool(arguments, url, timeout=900):
            calls.append(arguments)
            if "--list" in arguments:
                return SimpleNamespace(
                    stdout=(
                        b"1; 0 0 SCHEMA - public bank_app\n"
                        b"2; 1259 100 TABLE public accounts bank_app\n"
                        b"3; 1259 100 TABLE public buckets bank_app\n"
                        b"4; 1259 100 TABLE public customer_details "
                        b"supabase_admin\n"
                    )
                )
            if "--use-list" in arguments:
                restore_list = Path(
                    arguments[arguments.index("--use-list") + 1]
                )
                self.assertIn(
                    "TABLE public accounts",
                    restore_list.read_text(encoding="utf-8"),
                )
                self.assertNotIn(
                    "TABLE public buckets",
                    restore_list.read_text(encoding="utf-8"),
                )
                self.assertIn(
                    "TABLE public customer_details",
                    restore_list.read_text(encoding="utf-8"),
                )
                generated_sql = Path(
                    arguments[arguments.index("--file") + 1]
                )
                generated_sql.write_text(
                    "-- generated restore SQL\n", encoding="utf-8"
                )
            if "--single-transaction" in arguments:
                restore_sql = Path(
                    arguments[arguments.index("--file") + 1]
                ).read_text(encoding="utf-8")
                self.assertIn("DROP SCHEMA public CASCADE;", restore_sql)
                self.assertIn("CREATE SCHEMA public;", restore_sql)
                self.assertIn("-- generated restore SQL", restore_sql)
            return SimpleNamespace(stdout=b"")

        with self.app.app_context(), patch.object(
            database_backup, "_database_url", return_value=self.database_url
        ), patch.object(
            database_backup,
            "_utility_path",
            side_effect=lambda name: name,
        ), patch.object(
            database_backup, "_run_tool", side_effect=fake_run_tool
        ):
            database_backup.restore_backup(io.BytesIO(b"custom-format-dump"))

        restore_call = calls[-1]
        self.assertIn("--single-transaction", restore_call)
        self.assertIn("--schema=public", calls[1])
        self.assertIn("--no-owner", calls[1])
        self.assertNotIn("--clean", calls[1])
        self.assertNotIn("--if-exists", calls[1])
        self.assertEqual(restore_call[-1], "bank")

    def test_run_tool_disables_shell_execution(self):
        completed = SimpleNamespace(returncode=0, stderr=b"")
        with patch.object(
            database_backup,
            "_tool_environment",
            return_value=(os.environ.copy(), None),
        ), patch.object(
            database_backup.subprocess, "run", return_value=completed
        ) as subprocess_run:
            database_backup._run_tool(["pg_dump"], self.database_url)

        self.assertIs(subprocess_run.call_args.kwargs["shell"], False)


if __name__ == "__main__":
    unittest.main()
