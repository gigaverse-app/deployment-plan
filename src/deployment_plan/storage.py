"""Local durable receipts. Transactions make offline retries safe."""

import sqlite3
from pathlib import Path

from deployment_plan.models import Receipt


class LocalStore:
    def __init__(self, path: Path):
        self.path = path

    def read(self) -> list[Receipt]:
        if not self.path.exists():
            return []
        with sqlite3.connect(self.path) as connection:
            return [Receipt.model_validate_json(row[0]) for row in connection.execute("SELECT payload FROM receipts")]

    def append(self, receipt: Receipt) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS receipts (operation TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )
            connection.execute("BEGIN IMMEDIATE")
            previous = connection.execute(
                "SELECT payload FROM receipts WHERE operation = ?", (receipt.operation_id,)
            ).fetchone()
            if previous is not None:
                if Receipt.model_validate_json(previous[0]) != receipt:
                    raise ValueError(f"operation {receipt.operation_id} already exists with different content")
                return
            connection.execute("INSERT INTO receipts VALUES (?, ?)", (receipt.operation_id, receipt.model_dump_json()))
