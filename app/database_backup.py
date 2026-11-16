import logging
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from flask import current_app

from app.extensions import db


logger = logging.getLogger(__name__)
MAX_BACKUP_SIZE = 512 * 1024 * 1024


class DatabaseBackupError(Exception):
    """An expected, safe-to-display database backup or restore failure."""


def _windows_utility_path(name):
    installation_roots = {
        os.environ.get("ProgramFiles"),
        os.environ.get("ProgramFiles(x86)"),
    }
    candidates = []
    for root in filter(None, installation_roots):
        candidates.extend(
            Path(root).glob(f"PostgreSQL/*/bin/{name}.exe")
        )

    def version_key(path):
        install_directory = path.parent.parent.name
        return tuple(
            int(part) for part in re.findall(r"\d+", install_directory)
        )

    for candidate in sorted(candidates, key=version_key, reverse=True):
        if candidate.is_file():
            return str(candidate)
    return None


def _database_url():
    url = db.engine.url
    if url.get_backend_name() != "postgresql":
        raise DatabaseBackupError(
            "Database backup and restore require PostgreSQL."
        )
    return url


def _utility_path(name):
    config_key = {
        "pg_dump": "PG_DUMP_PATH",
        "pg_restore": "PG_RESTORE_PATH",
        "psql": "PSQL_PATH",
    }.get(name)
    if config_key is None:
        raise DatabaseBackupError("Unsupported PostgreSQL utility.")

    configured = current_app.config.get(config_key) or os.getenv(config_key)
    if configured:
        configured_path = Path(configured).expanduser()
        utility = (
            str(configured_path)
            if configured_path.is_file()
            else shutil.which(configured)
        )
    else:
        utility = shutil.which(name)
        if utility is None and os.name == "nt":
            utility = _windows_utility_path(name)

    if not utility or not Path(utility).is_file():
        raise DatabaseBackupError(
            "PostgreSQL backup utilities are unavailable on this server."
        )
    return str(Path(utility).resolve())


def _escape_passfile_field(value):
    return str(value).replace("\\", "\\\\").replace(":", "\\:")


def _tool_environment(url):
    environment = os.environ.copy()
    for key in (
        "PGPASSWORD",
        "PGPASSFILE",
        "PGSERVICE",
        "PGSERVICEFILE",
        "PGHOSTADDR",
        "PGOPTIONS",
        "PGHOST",
        "PGPORT",
        "PGUSER",
        "PGDATABASE",
        "PGSSLMODE",
        "PGSSLROOTCERT",
        "PGSSLCERT",
        "PGSSLKEY",
    ):
        environment.pop(key, None)

    for key, value in (
        ("PGHOST", url.host),
        ("PGPORT", str(url.port) if url.port else None),
        ("PGUSER", url.username),
        ("PGDATABASE", url.database),
    ):
        if value is not None:
            environment[key] = value

    for query_key, environment_key in (
        ("sslmode", "PGSSLMODE"),
        ("sslrootcert", "PGSSLROOTCERT"),
        ("sslcert", "PGSSLCERT"),
        ("sslkey", "PGSSLKEY"),
    ):
        value = url.query.get(query_key)
        if value:
            environment[environment_key] = str(value)

    passfile = None
    if url.password is not None:
        if "\n" in url.password or "\r" in url.password:
            raise DatabaseBackupError(
                "Unable to use the configured PostgreSQL credentials."
            )
        fields = (
            url.host or "*",
            str(url.port) if url.port else "*",
            url.database or "*",
            url.username or "*",
            url.password,
        )
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                delete=False,
                prefix="jab-pgpass-",
            ) as file:
                passfile = Path(file.name)
                file.write(
                    ":".join(_escape_passfile_field(field) for field in fields)
                )
                file.write("\n")
            if os.name != "nt":
                passfile.chmod(0o600)
            environment["PGPASSFILE"] = str(passfile)
        except OSError as error:
            if passfile:
                passfile.unlink(missing_ok=True)
            logger.error(
                "Could not prepare PostgreSQL credentials: error_type=%s",
                type(error).__name__,
            )
            raise DatabaseBackupError(
                "Unable to complete the database operation. Check the server logs."
            ) from error

    return environment, passfile


def _run_tool(arguments, url, timeout=900):
    passfile = None
    try:
        environment, passfile = _tool_environment(url)
        result = subprocess.run(
            arguments,
            check=False,
            capture_output=True,
            timeout=timeout,
            env=environment,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        logger.error(
            "PostgreSQL utility failed: error_type=%s",
            type(error).__name__,
        )
        raise DatabaseBackupError(
            "Unable to complete the database operation. Check the server logs."
        ) from error
    finally:
        if passfile:
            try:
                passfile.unlink(missing_ok=True)
            except OSError as error:
                logger.error(
                    "Could not remove temporary PostgreSQL credentials: "
                    "error_type=%s",
                    type(error).__name__,
                )
                raise DatabaseBackupError(
                    "Unable to complete the database operation. "
                    "Check the server logs."
                ) from error

    if result.returncode:
        logger.error(
            "PostgreSQL utility returned an error: return_code=%s stderr=%s",
            result.returncode,
            result.stderr.decode("utf-8", errors="replace")[-2000:],
        )
        raise DatabaseBackupError(
            "PostgreSQL could not complete the database operation. "
            "Check the server logs."
        )
    return result


def create_backup():
    url = _database_url()
    try:
        temporary_directory = tempfile.TemporaryDirectory(
            prefix="jab-database-backup-"
        )
    except OSError as error:
        raise DatabaseBackupError(
            "Unable to create a temporary database backup."
        ) from error

    dump_path = Path(temporary_directory.name) / "jab-bank-database.dump"
    filename = (
        f"jab-bank-database-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.dump"
    )
    try:
        arguments = [
            _utility_path("pg_dump"),
            "--format=custom",
            "--schema=public",
            "--no-owner",
            "--no-privileges",
            "--file",
            str(dump_path),
        ]
        _run_tool(arguments, url)
        if not dump_path.is_file() or dump_path.stat().st_size == 0:
            raise DatabaseBackupError(
                "PostgreSQL did not create a usable database backup."
            )
        if dump_path.stat().st_size > MAX_BACKUP_SIZE:
            raise DatabaseBackupError(
                "The generated backup exceeds the 512 MB size limit."
            )
    except OSError as error:
        temporary_directory.cleanup()
        raise DatabaseBackupError(
            "Unable to create a database backup. Check the server logs."
        ) from error
    except DatabaseBackupError:
        temporary_directory.cleanup()
        raise

    return temporary_directory, dump_path, filename


def _write_restore_list(list_path, listing):
    excluded_markers = (
        "event trigger",
        " auth.",
        " storage.",
        "rls_auto_enable",
        "ensure_rls",
        "pgrst_drop_watch",
    )
    managed_object_markers = (
        " bucket_",
        " s3_",
        " vector_",
        " objects ",
        " buckets ",
        " migrations ",
        " prefixes ",
        " objects_id_seq",
        " webauthn_",
        " fido_",
        " sso_",
        " pgbouncer",
    )
    try:
        with list_path.open("w", encoding="utf-8") as restore_list:
            for line in listing.stdout.decode(
                "utf-8", errors="replace"
            ).splitlines(keepends=True):
                normalized_line = " ".join(line.lower().split())
                is_non_public_schema = any(
                    f" {schema_name} " in f" {normalized_line} "
                    for schema_name in (
                        "pgbouncer",
                        "pg_catalog",
                        "information_schema",
                    )
                )
                is_managed_object = any(
                    marker in f" {normalized_line} "
                    for marker in managed_object_markers
                )
                if (
                    not is_non_public_schema
                    and not is_managed_object
                    and not any(
                        marker in normalized_line
                        for marker in excluded_markers
                    )
                ):
                    restore_list.write(line)
    except OSError as error:
        raise DatabaseBackupError(
            "Unable to prepare the database restore."
        ) from error


def restore_backup(upload_stream):
    url = _database_url()
    try:
        temporary_directory = tempfile.TemporaryDirectory(
            prefix="jab-database-restore-"
        )
    except OSError as error:
        raise DatabaseBackupError(
            "Unable to prepare the database restore."
        ) from error

    temp = Path(temporary_directory.name)
    dump_path = temp / "uploaded.dump"
    restore_list_path = temp / "restore.list"
    generated_sql_path = temp / "generated_restore.sql"
    restore_sql_path = temp / "restore.sql"

    try:
        size = 0
        with dump_path.open("xb") as staged_upload:
            while True:
                chunk = upload_stream.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_BACKUP_SIZE:
                    raise DatabaseBackupError(
                        "The uploaded backup exceeds the 512 MB size limit."
                    )
                staged_upload.write(chunk)
        if size == 0:
            raise DatabaseBackupError("Choose a non-empty PostgreSQL backup file.")

        listing = _run_tool(
            [_utility_path("pg_restore"), "--list", str(dump_path)],
            url,
            timeout=120,
        )
        _write_restore_list(restore_list_path, listing)

        _run_tool(
            [
                _utility_path("pg_restore"),
                "--schema=public",
                "--no-owner",
                "--no-privileges",
                "--exit-on-error",
                "--file",
                str(generated_sql_path),
                "--use-list",
                str(restore_list_path),
                str(dump_path),
            ],
            url,
        )
        if (
            not generated_sql_path.is_file()
            or generated_sql_path.stat().st_size == 0
        ):
            raise DatabaseBackupError(
                "Unable to prepare the database restore."
            )

        try:
            with restore_sql_path.open("wb") as restore_sql:
                restore_sql.write(b"SET LOCAL lock_timeout = '10s';\n")
                restore_sql.write(b"SET LOCAL statement_timeout = '10min';\n")
                restore_sql.write(b"DROP SCHEMA public CASCADE;\n")
                restore_sql.write(b"CREATE SCHEMA public;\n")
                with generated_sql_path.open("rb") as generated_sql:
                    shutil.copyfileobj(generated_sql, restore_sql)
        except OSError as error:
            raise DatabaseBackupError(
                "Unable to prepare the database restore."
            ) from error

        db.session.remove()
        db.engine.dispose()
        _run_tool(
            [
                _utility_path("psql"),
                "--set=ON_ERROR_STOP=on",
                "--single-transaction",
                "--file",
                str(restore_sql_path),
                "--dbname",
                url.database,
            ],
            url,
            timeout=660,
        )
    except (OSError, ValueError) as error:
        logger.error(
            "Database restore failed: error_type=%s",
            type(error).__name__,
        )
        raise DatabaseBackupError(
            "Unable to restore the uploaded database backup."
        ) from error
    except DatabaseBackupError:
        raise
    finally:
        temporary_directory.cleanup()
