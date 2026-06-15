"""Harness progress artifact classifier context."""

from __future__ import annotations

from agloom.harness.progress import ProgressArtifact


def test_classifier_context_no_tasks_not_finished() -> None:
    artifact = ProgressArtifact(description="Build RCA platform")
    text = artifact.to_classifier_context()
    assert "no tasks yet" in text.lower()
    assert "finished" not in text.lower()
    assert "Build RCA platform" in text


def test_classifier_context_no_tasks_no_goal() -> None:
    artifact = ProgressArtifact()
    text = artifact.to_classifier_context()
    assert "initialize_project" in text


def test_classifier_context_all_passing_with_tasks() -> None:
    from agloom.harness.progress import Task, TaskPriority, TaskStatus

    artifact = ProgressArtifact(
        tasks=[
            Task(
                id="t1",
                description="done",
                category="general",
                priority=TaskPriority.MEDIUM,
                status=TaskStatus.PASSING,
            )
        ]
    )
    text = artifact.to_classifier_context()
    assert "1/1" in text
    assert "passing" in text.lower()
