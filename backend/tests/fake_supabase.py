"""Tiny in-memory stand-in for the Supabase client (tables only), used by the ticket/doc tests."""
import types
import uuid
from datetime import datetime, timedelta, timezone


class FakeQuery:
    def __init__(self, db, table):
        self.db, self.table = db, table
        self.op = self.payload = self.order_by = self.range_ = self.limit_ = None
        self.cols = None
        self.filters = []

    def select(self, columns="*"):
        self.op = "select"
        self.cols = None if columns.strip() == "*" else [c.strip() for c in columns.split(",")]
        return self
    def insert(self, payload): self.op, self.payload = "insert", payload; return self
    def update(self, payload): self.op, self.payload = "update", payload; return self
    def eq(self, key, value): self.filters.append(("eq", key, value)); return self
    def gte(self, key, value): self.filters.append(("gte", key, value)); return self
    def order(self, column, desc=False): self.order_by = (column, desc); return self
    def range(self, start, end): self.range_ = (start, end); return self
    def limit(self, n): self.limit_ = n; return self

    def _match(self, row):
        for kind, key, value in self.filters:
            if kind == "eq" and row.get(key) != value:
                return False
            if kind == "gte" and not row.get(key) >= value:
                return False
        return True

    def execute(self):
        if f"{self.op}:{self.table}" in self.db.fail:
            raise RuntimeError("boom")
        rows = self.db.tables.setdefault(self.table, [])
        if self.op == "insert":
            new = [self.db.fill(self.table, p) for p in (self.payload if isinstance(self.payload, list) else [self.payload])]
            rows.extend(new)
            return types.SimpleNamespace(data=[dict(r) for r in new])
        match = [r for r in rows if self._match(r)]
        if self.op == "update":
            for r in match:
                r.update(self.payload)
                if "updated_at" in r:
                    r["updated_at"] = self.db.now()
        else:
            if self.order_by:
                match = sorted(match, key=lambda r: r[self.order_by[0]], reverse=self.order_by[1])
            if self.range_:
                match = match[self.range_[0]: self.range_[1] + 1]
            if self.limit_ is not None:
                match = match[: self.limit_]
        if self.cols:  # like PostgREST, only return the selected columns
            return types.SimpleNamespace(data=[{c: r[c] for c in self.cols} for r in match])
        return types.SimpleNamespace(data=[dict(r) for r in match])


class FakeDB:
    """Applies the same defaults as the real schema (ticket numbers, status, timestamps...)."""

    def __init__(self, fail=()):
        self.tables, self.fail = {}, set(fail)
        self._clock, self._ticket_seq = datetime.now(timezone.utc), 1000

    def now(self):
        self._clock += timedelta(milliseconds=1)
        return self._clock.isoformat()

    def table(self, name):
        return FakeQuery(self, name)

    def fill(self, table, payload):
        row = {"id": str(uuid.uuid4()), "created_at": self.now(), **payload}
        if table == "tickets":
            self._ticket_seq += 1
            row = {"ticket_number": f"TKT-{self._ticket_seq}", "description": "", "category": "general",
                   "priority": "medium", "status": "open", "updated_at": row["created_at"], **row}
        if table == "generated_documents":
            row.setdefault("related_ticket_id", None)
        return row
