from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

N, R, P, DKLEN = 16384, 8, 1, 32
SESSION_TTL = 7 * 24 * 3600


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=N,
        r=R,
        p=P,
        dklen=DKLEN,
    )
    return f"scrypt${N}${R}${P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    parts = stored.split("$")
    if len(parts) != 6 or parts[0] != "scrypt":
        return False
    try:
        n, r, p = int(parts[1]), int(parts[2]), int(parts[3])
        salt = bytes.fromhex(parts[4])
        expected = bytes.fromhex(parts[5])
    except ValueError:
        return False
    actual = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        dklen=len(expected),
    )
    return secrets.compare_digest(actual, expected)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass
class Operator:
    id: str
    email: str
    created_at: str
    last_login_at: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "email": self.email,
            "createdAt": self.created_at,
            "lastLoginAt": self.last_login_at,
        }


class OperatorStore:
    def __init__(self, hub_root: Path) -> None:
        self.root = Path(hub_root)
        console = self.root / "console"
        console.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(console, 0o700)
        except OSError:
            pass
        self.db_path = console / "operators.sqlite"
        self._db = sqlite3.connect(self.db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys = ON")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS operators (
              id TEXT PRIMARY KEY,
              email TEXT NOT NULL UNIQUE,
              password_hash TEXT NOT NULL,
              created_at TEXT NOT NULL,
              last_login_at TEXT
            );
            CREATE TABLE IF NOT EXISTS sessions (
              id TEXT PRIMARY KEY,
              operator_id TEXT NOT NULL REFERENCES operators(id),
              token_hash TEXT NOT NULL UNIQUE,
              csrf TEXT NOT NULL,
              expires_at INTEGER NOT NULL,
              created_at TEXT NOT NULL,
              revoked_at TEXT
            );
            """
        )
        self._db.commit()
        try:
            os.chmod(self.db_path, 0o600)
        except OSError:
            pass

    def count(self) -> int:
        row = self._db.execute("SELECT COUNT(*) AS n FROM operators").fetchone()
        return int(row["n"] if row else 0)

    def list_operators(self) -> list[Operator]:
        rows = self._db.execute(
            "SELECT id, email, created_at, last_login_at FROM operators ORDER BY created_at"
        ).fetchall()
        return [self._op(r) for r in rows]

    def create(self, email: str, password: str) -> Operator:
        oid = "op_" + secrets.token_hex(12)
        created = _now()
        self._db.execute(
            "INSERT INTO operators (id, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
            (oid, email, hash_password(password), created),
        )
        self._db.commit()
        return Operator(oid, email, created, None)

    def authenticate(self, email: str, password: str) -> Operator | None:
        row = self._db.execute(
            "SELECT id, email, password_hash, created_at, last_login_at FROM operators WHERE email = ?",
            (email,),
        ).fetchone()
        if not row or not verify_password(password, row["password_hash"]):
            return None
        return self._op(row)

    def create_session(self, operator: Operator) -> tuple[str, str]:
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        sid = "opsess_" + secrets.token_hex(12)
        expires = int(time.time()) + SESSION_TTL
        self._db.execute(
            """INSERT INTO sessions (id, operator_id, token_hash, csrf, expires_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (sid, operator.id, hash_token(token), csrf, expires, _now()),
        )
        self._db.execute(
            "UPDATE operators SET last_login_at = ? WHERE id = ?",
            (_now(), operator.id),
        )
        self._db.commit()
        return token, csrf

    def auth_session(self, token: str) -> tuple[Operator, str] | None:
        if not token:
            return None
        row = self._db.execute(
            """SELECT o.id, o.email, o.created_at, o.last_login_at, s.csrf, s.expires_at, s.revoked_at
               FROM sessions s JOIN operators o ON o.id = s.operator_id
               WHERE s.token_hash = ?""",
            (hash_token(token),),
        ).fetchone()
        if not row or row["revoked_at"] is not None:
            return None
        if int(row["expires_at"]) <= int(time.time()):
            return None
        return self._op(row), str(row["csrf"])

    def revoke_session(self, token: str) -> None:
        self._db.execute(
            "UPDATE sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
            (_now(), hash_token(token)),
        )
        self._db.commit()

    @staticmethod
    def _op(row: sqlite3.Row) -> Operator:
        return Operator(
            id=str(row["id"]),
            email=str(row["email"]),
            created_at=str(row["created_at"]),
            last_login_at=row["last_login_at"],
        )
