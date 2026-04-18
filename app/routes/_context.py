from app import fs, pipeline, store


def nav_counts() -> dict:
    """Context keys the base template needs on every page."""
    return {
        "speakers_count": len(fs.list_unknown_clips()),
        "pipeline_running": pipeline.get_runner().is_running(),
        "inbox_count": len(store.list_pending_proposals()),
    }
