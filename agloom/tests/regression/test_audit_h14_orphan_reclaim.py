"""H14: orphan IN_PROGRESS tasks are reclaimed by another session."""

from agloom.harness.progress import ProgressArtifact, Task, TaskPriority, TaskStatus


def test_orphan_in_progress_reclaimed_by_new_session():
    artifact = ProgressArtifact(
        project_name="p",
        agent_name="a",
        description="goal",
        tasks=[
            Task(
                id="t1",
                category="functional",
                description="verify logs",
                status=TaskStatus.IN_PROGRESS,
                priority=TaskPriority.HIGH,
                assigned_session="crashed-session",
            )
        ],
    )
    nxt = artifact.get_next_task("recovery-session")
    assert nxt is not None
    assert nxt.id == "t1"
    assert nxt.assigned_session == "recovery-session"
