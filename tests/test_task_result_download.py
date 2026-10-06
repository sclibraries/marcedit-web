"""Completed synchronous task results must remain downloadable (TASK-254)."""

from streamlit.testing.v1 import AppTest


def test_completed_task_result_can_prepare_output_download(tmp_path):
    """Exercise the result renderer and real download helper across a rerun."""
    output = tmp_path / "output.mrc"
    output.write_bytes(b"task-output")

    def app(output_path):
        import streamlit as st
        from marcedit_web.render import tasks

        st.session_state[tasks.K_SYNC_RUN_RESULT] = {
            "input_count": 1,
            "output_count": 1,
            "error_count": 0,
            "task_names": ["cleanup"],
            "timed_out": False,
            "returncode": 0,
            "stderr": "",
            "errors": [],
            "diff_summary": None,
            "output_path": output_path,
            "filename": "vendor_tasks.mrc",
        }
        tasks._render_sync_run_result()

    at = AppTest.from_function(app, args=(str(output),)).run(timeout=15)

    assert not at.exception
    assert not at.get("download_button")
    at.button(key="tasks_sync_download_prepare").click().run(timeout=15)
    assert not at.exception
    downloads = at.get("download_button")
    assert len(downloads) == 1
    assert downloads[0].label == "Download vendor_tasks.mrc"
