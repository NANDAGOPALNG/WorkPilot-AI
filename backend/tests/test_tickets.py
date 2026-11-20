import pytest

from app.services import ticket_service as svc
from app.services.ticket_service import TicketError
from fake_supabase import FakeDB


def make(db, title="Laptop will not boot", **kw):
    return svc.create_ticket({"title": title, **kw}, db=db)


# ------------------------------------------------------------------ creation
def test_create_uses_database_defaults_and_numbers():
    db = FakeDB()
    ticket, created = make(db)
    assert created and ticket["ticket_number"] == "TKT-1001" and ticket["id"]
    assert (ticket["status"], ticket["priority"], ticket["category"]) == ("open", "medium", "general")
    second, _ = make(db, title="Printer jam")
    assert second["ticket_number"] == "TKT-1002"


def test_create_normalises_input_and_validates():
    ticket, _ = make(FakeDB(), title="  Spaced  ", category=" Hardware ", priority="high", description=" x ")
    assert (ticket["title"], ticket["category"], ticket["priority"], ticket["description"]) == ("Spaced", "hardware", "high", "x")
    for bad in ({"title": "   "}, {"title": "ok", "priority": "urgent"}):
        with pytest.raises(TicketError) as e:
            svc.create_ticket(bad, db=FakeDB())
        assert e.value.status_code == 422


def test_create_ignores_client_supplied_identifiers():
    db = FakeDB()
    ticket, _ = svc.create_ticket({"title": "t", "ticket_number": "TKT-9", "id": "x", "status": "closed"}, db=db)
    assert ticket["ticket_number"] == "TKT-1001" and ticket["status"] == "open" and ticket["id"] != "x"


def test_repeated_identical_request_does_not_create_duplicate(monkeypatch):
    db = FakeDB()
    first, created1 = make(db, description="same")
    again, created2 = make(db, description="same")
    assert created1 and not created2 and again["id"] == first["id"] and len(db.tables["tickets"]) == 1
    _, created3 = make(db, description="different")
    assert created3 and len(db.tables["tickets"]) == 2
    monkeypatch.setattr(svc, "DUPLICATE_WINDOW_SECONDS", -60)  # simulate the window having passed
    _, created4 = make(db, description="same")
    assert created4


def test_create_database_failure():
    with pytest.raises(TicketError) as e:
        make(FakeDB(fail={"insert:tickets"}))
    assert e.value.status_code == 500


# ------------------------------------------------------------------- listing
def test_list_filters_order_and_pagination():
    db = FakeDB()
    a, _ = make(db, title="A", priority="low")
    b, _ = make(db, title="B", priority="high")
    c, _ = make(db, title="C", priority="high")
    svc.update_ticket(c["id"], {"status": "resolved"}, db=db)

    assert [t["title"] for t in svc.list_tickets(db=db)["tickets"]] == ["C", "B", "A"]  # newest first
    assert {t["title"] for t in svc.list_tickets(priority="high", db=db)["tickets"]} == {"B", "C"}
    assert [t["title"] for t in svc.list_tickets(status="resolved", db=db)["tickets"]] == ["C"]
    page = svc.list_tickets(limit=1, offset=1, db=db)
    assert [t["title"] for t in page["tickets"]] == ["B"] and page["limit"] == 1 and page["offset"] == 1
    assert set(svc.list_tickets(db=db)["tickets"][0]) == set(svc.COLUMNS.split(","))


# ----------------------------------------------------------------- retrieval
def test_get_by_uuid_and_ticket_number_and_404():
    db = FakeDB()
    ticket, _ = make(db)
    assert svc.get_ticket(ticket["id"], db=db)["id"] == ticket["id"]
    assert svc.get_ticket("tkt-1001", db=db)["id"] == ticket["id"]
    for missing in ("TKT-9999", "3f2b1c9e-8a7d-4c55-9a0e-0d6f1b2c3d4e"):
        with pytest.raises(TicketError) as e:
            svc.get_ticket(missing, db=db)
        assert e.value.status_code == 404
    with pytest.raises(TicketError) as e:
        svc.get_ticket("not-a-ticket", db=db)
    assert e.value.status_code == 422


# -------------------------------------------------------------------- update
def test_update_changes_only_supplied_fields():
    db = FakeDB()
    ticket, _ = make(db, description="orig", priority="low")
    updated = svc.update_ticket(ticket["ticket_number"], {"status": "in_progress", "priority": "critical"}, db=db)
    assert (updated["status"], updated["priority"]) == ("in_progress", "critical")
    assert updated["title"] == ticket["title"] and updated["description"] == "orig"
    assert updated["updated_at"] > ticket["updated_at"]
    assert svc.update_ticket(ticket["id"], {"title": " New ", "status": None}, db=db)["status"] == "in_progress"


def test_update_rejects_bad_values_protected_fields_and_missing_tickets():
    db = FakeDB()
    ticket, _ = make(db)
    for bad in ({"status": "done"}, {"priority": "urgent"}, {"title": "  "}, {}, {"ticket_number": "TKT-5"}, {"id": "x"}):
        with pytest.raises(TicketError) as e:
            svc.update_ticket(ticket["id"], bad, db=db)
        assert e.value.status_code == 422
    assert db.tables["tickets"][0]["ticket_number"] == "TKT-1001"
    with pytest.raises(TicketError) as e:
        svc.update_ticket("TKT-4040", {"status": "closed"}, db=db)
    assert e.value.status_code == 404
    with pytest.raises(TicketError) as e:
        svc.update_ticket(ticket["id"], {"status": "closed"}, db=FakeDB(fail={"update:tickets"}))
    assert e.value.status_code == 500
