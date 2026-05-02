"""Tests for src/agents/coding/pending.py — PendingStore, DevPlanStore, SnapshotStore."""
import pytest
from pathlib import Path

from src.agents.coding.pending import (
    FileChange, PendingStore, DevPlanStore, SnapshotStore,
)


# ── PendingStore ──────────────────────────────────────────────────────────────

def make_change(path="/proj/app.py", original="old", proposed="new", desc="fix"):
    return FileChange(path=path, original=original, proposed=proposed, description=desc)


def test_pending_store_starts_empty():
    store = PendingStore()
    assert not store
    assert len(store) == 0


def test_pending_store_add():
    store = PendingStore()
    store.add(make_change())
    assert len(store) == 1


def test_pending_store_add_replaces_same_path():
    store = PendingStore()
    store.add(make_change(proposed="v1"))
    store.add(make_change(proposed="v2"))
    assert len(store) == 1
    assert store.items[0].proposed == "v2"


def test_pending_store_add_different_paths():
    store = PendingStore()
    store.add(make_change(path="/a.py"))
    store.add(make_change(path="/b.py"))
    assert len(store) == 2


def test_pending_store_pop_all_clears():
    store = PendingStore()
    store.add(make_change(path="/a.py"))
    store.add(make_change(path="/b.py"))
    items = store.pop_all()
    assert len(items) == 2
    assert len(store) == 0


def test_pending_store_pop_latest():
    store = PendingStore()
    store.add(make_change(path="/a.py"))
    store.add(make_change(path="/b.py"))
    latest = store.pop_latest()
    assert latest.path == "/b.py"
    assert len(store) == 1


def test_pending_store_pop_latest_empty():
    store = PendingStore()
    assert store.pop_latest() is None


def test_pending_store_clear():
    store = PendingStore()
    store.add(make_change())
    store.clear()
    assert not store


def test_pending_store_items_returns_copy():
    store = PendingStore()
    store.add(make_change())
    items = store.items
    items.clear()
    assert len(store) == 1  # internal list unaffected


# ── DevPlanStore ──────────────────────────────────────────────────────────────

def test_dev_plan_starts_empty():
    plan = DevPlanStore()
    assert not plan
    assert plan.steps == []


def test_dev_plan_create():
    plan = DevPlanStore()
    plan.create(["Step A", "Step B", "Step C"])
    assert len(plan.steps) == 3
    assert plan.steps[0].label == "Step A"
    assert not plan.steps[0].done


def test_dev_plan_create_overwrites_previous():
    plan = DevPlanStore()
    plan.create(["Old step"])
    plan.create(["New step 1", "New step 2"])
    assert len(plan.steps) == 2
    assert plan.steps[0].label == "New step 1"


def test_dev_plan_check_marks_done():
    plan = DevPlanStore()
    plan.create(["A", "B"])
    changed = plan.check(0)
    assert changed is True
    assert plan.steps[0].done


def test_dev_plan_check_returns_false_if_already_done():
    plan = DevPlanStore()
    plan.create(["A"])
    plan.check(0)
    changed = plan.check(0)
    assert changed is False


def test_dev_plan_check_out_of_range_returns_false():
    plan = DevPlanStore()
    plan.create(["A"])
    assert plan.check(5) is False
    assert plan.check(-1) is False


def test_dev_plan_next_pending_index():
    plan = DevPlanStore()
    plan.create(["A", "B", "C"])
    assert plan.next_pending_index == 0
    plan.check(0)
    assert plan.next_pending_index == 1
    plan.check(1)
    assert plan.next_pending_index == 2
    plan.check(2)
    assert plan.next_pending_index is None


def test_dev_plan_steps_returns_copy():
    plan = DevPlanStore()
    plan.create(["A", "B"])
    steps = plan.steps
    steps.clear()
    assert len(plan.steps) == 2  # internal list unaffected


def test_dev_plan_bool():
    plan = DevPlanStore()
    assert not plan
    plan.create(["A"])
    assert plan


def test_dev_plan_clear():
    plan = DevPlanStore()
    plan.create(["A", "B"])
    plan.clear()
    assert not plan


# ── SnapshotStore ─────────────────────────────────────────────────────────────

def test_snapshot_store_starts_empty():
    store = SnapshotStore()
    assert not store
    assert store.paths == []


def test_snapshot_save_and_restore(tmp_path):
    store = SnapshotStore()
    f = tmp_path / "app.py"
    f.write_text("original content")
    store.save(str(f), "original content")
    f.write_text("modified content")
    result = store.restore(str(f))
    assert result is True
    assert f.read_text() == "original content"


def test_snapshot_save_keeps_oldest():
    store = SnapshotStore()
    store.save("/proj/app.py", "v1")
    store.save("/proj/app.py", "v2")  # should be ignored
    assert store._data["/proj/app.py"] == "v1"


def test_snapshot_restore_nonexistent_returns_false():
    store = SnapshotStore()
    result = store.restore("/nonexistent/path.py")
    assert result is False


def test_snapshot_restore_removes_entry(tmp_path):
    store = SnapshotStore()
    f = tmp_path / "f.py"
    f.write_text("x")
    store.save(str(f), "x")
    store.restore(str(f))
    assert str(f) not in store._data


def test_snapshot_restore_all(tmp_path):
    store = SnapshotStore()
    f1 = tmp_path / "a.py"
    f2 = tmp_path / "b.py"
    f1.write_text("a-modified")
    f2.write_text("b-modified")
    store.save(str(f1), "a-original")
    store.save(str(f2), "b-original")
    restored = store.restore_all()
    assert sorted(restored) == sorted([str(f1), str(f2)])
    assert f1.read_text() == "a-original"
    assert f2.read_text() == "b-original"
    assert not store


def test_snapshot_paths():
    store = SnapshotStore()
    store.save("/a.py", "a")
    store.save("/b.py", "b")
    assert set(store.paths) == {"/a.py", "/b.py"}


def test_snapshot_clear():
    store = SnapshotStore()
    store.save("/a.py", "a")
    store.clear()
    assert not store
