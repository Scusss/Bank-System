import io
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from flask import Blueprint, Flask

from app.extensions import db
from app.routes import admin as admin_routes


class AdminDatabaseBackupRouteTests(unittest.TestCase):
    def setUp(self):
        project_root = Path(__file__).resolve().parents[1]
        self.app = Flask(
            __name__,
            template_folder=str(project_root / "templates"),
            static_folder=str(project_root / "static"),
        )
        self.app.config.update(
            SECRET_KEY="test-secret",
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
        )
        db.init_app(self.app)

        auth = Blueprint("auth", __name__)
        auth.add_url_rule(
            "/login", endpoint="login", view_func=lambda: "login"
        )
        auth.add_url_rule(
            "/logout", endpoint="logout", view_func=lambda: "logout"
        )
        verification = Blueprint("verification", __name__)
        verification.add_url_rule(
            "/verification",
            endpoint="dashboard",
            view_func=lambda: "verification",
        )
        self.app.register_blueprint(auth)
        self.app.register_blueprint(verification)
        self.app.register_blueprint(admin_routes.admin)
        self.client = self.app.test_client()

    def _sign_in_admin(self):
        with self.client.session_transaction() as browser_session:
            browser_session["customer_id"] = (
                "123e4567-e89b-12d3-a456-426614174000"
            )
            browser_session["database_backup_csrf"] = "valid-token"

    def test_backup_page_rejects_anonymous_requests(self):
        response = self.client.get("/admin/database-backup")

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_backup_page_rejects_non_admin_users(self):
        self._sign_in_admin()
        customer = SimpleNamespace(account_status="active", is_locked=False)
        with patch.object(
            admin_routes.db.session, "get", return_value=customer
        ), patch.object(
            admin_routes, "is_access_blocked", return_value=False
        ), patch.object(
            admin_routes, "is_admin", return_value=False
        ):
            response = self.client.get("/admin/database-backup")

        self.assertEqual(response.status_code, 403)

    def test_admin_can_render_backup_page(self):
        self._sign_in_admin()
        customer = SimpleNamespace(account_status="active", is_locked=False)
        with patch.object(
            admin_routes.db.session, "get", return_value=customer
        ), patch.object(
            admin_routes, "is_access_blocked", return_value=False
        ), patch.object(
            admin_routes, "is_admin", return_value=True
        ):
            response = self.client.get("/admin/database-backup")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Restore a database backup", response.data)
        self.assertIn("no-store", response.headers["Cache-Control"])

    def test_backup_download_cleans_up_its_temporary_file(self):
        self._sign_in_admin()
        with self.client.session_transaction() as browser_session:
            browser_session.pop("database_backup_csrf", None)
        customer = SimpleNamespace(account_status="active", is_locked=False)
        temporary_directory = tempfile.TemporaryDirectory()
        dump_path = Path(temporary_directory.name) / "backup.dump"
        dump_path.write_bytes(b"custom-format-dump")
        with patch.object(
            admin_routes.db.session, "get", return_value=customer
        ), patch.object(
            admin_routes, "is_access_blocked", return_value=False
        ), patch.object(
            admin_routes, "is_admin", return_value=True
        ), patch.object(
            admin_routes,
            "create_backup",
            return_value=(temporary_directory, dump_path, "backup.dump"),
        ):
            page = self.client.get("/admin/database-backup")
            token_match = re.search(
                rb'name="csrf_token" value="([^"]+)"',
                page.data,
            )
            self.assertIsNotNone(token_match)
            response = self.client.post(
                "/admin/database-backup/download",
                data={"csrf_token": token_match.group(1).decode("ascii")},
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.data, b"custom-format-dump")
            response.close()

        self.assertFalse(Path(temporary_directory.name).exists())

    def test_restore_requires_csrf_and_destructive_confirmation(self):
        self._sign_in_admin()
        customer = SimpleNamespace(
            account_status="active",
            is_locked=False,
        )
        with patch.object(
            admin_routes.db.session, "get", return_value=customer
        ), patch.object(
            admin_routes, "is_access_blocked", return_value=False
        ), patch.object(
            admin_routes, "is_admin", return_value=True
        ), patch.object(
            admin_routes, "restore_backup"
        ) as restore:
            invalid_csrf = self.client.post(
                "/admin/database-backup/restore",
                data={"csrf_token": "wrong"},
            )
            self.assertEqual(invalid_csrf.status_code, 302)
            restore.assert_not_called()

            missing_confirmation = self.client.post(
                "/admin/database-backup/restore",
                data={
                    "csrf_token": "valid-token",
                    "backup_file": (io.BytesIO(b"dump"), "backup.dump"),
                },
            )
            self.assertEqual(missing_confirmation.status_code, 302)
            restore.assert_not_called()

            confirmed = self.client.post(
                "/admin/database-backup/restore",
                data={
                    "csrf_token": "valid-token",
                    "confirm_restore": "yes",
                    "confirm_phrase": "RESTORE",
                    "backup_file": (io.BytesIO(b"dump"), "backup.dump"),
                },
            )
            self.assertEqual(confirmed.status_code, 302)
            restore.assert_called_once()


if __name__ == "__main__":
    unittest.main()
