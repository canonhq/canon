"""Tests for the Tasks API ?expand=acs parameter."""

from canon.web.models import TaskItem


def test_task_item_has_acceptance_criteria_field():
    """TaskItem should have an optional acceptance_criteria field."""
    item = TaskItem(
        section_id="1",
        title="Test",
        status="todo",
        acceptance_criteria=[
            {"text": "AC one", "checked": False},
            {"text": "AC two", "checked": True},
        ],
    )
    assert len(item.acceptance_criteria) == 2
    assert item.acceptance_criteria[0]["text"] == "AC one"
    assert item.acceptance_criteria[0]["checked"] is False
    assert item.acceptance_criteria[1]["checked"] is True


def test_task_item_acceptance_criteria_defaults_empty():
    """When not provided, acceptance_criteria should default to empty list."""
    item = TaskItem(section_id="1", title="Test", status="todo")
    assert item.acceptance_criteria == []
