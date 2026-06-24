"""schedule_store degrades to a safe no-op without Supabase — same contract as brand_memory."""
from src.memory import schedule_store


def test_disabled_without_supabase(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    # None of these should raise or touch a client when Supabase is not configured.
    schedule_store.enqueue_scheduled({"post_id": "post_1"}, "thread_1")
    schedule_store.mark_dispatched("post_1")
    assert schedule_store.fetch_due() == []
