"""Schedule-node routing — rejected posts must never be enqueued for dispatch."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from src.graph import _schedule_node
from src.schemas import PostAsset


def _future_asset(status):
    when = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()
    return PostAsset(campaign_id="c1", caption="x", approval_status=status,
                     scheduled_at=when).model_dump(mode="json")


def test_schedule_node_enqueues_approved_future_post():
    with patch("src.graph.enqueue_scheduled") as enq:
        _schedule_node({"thread_id": "t", "creative_assets": [_future_asset("approved")], "status": "s"})
    enq.assert_called_once()


def test_schedule_node_skips_rejected_future_post():
    with patch("src.graph.enqueue_scheduled") as enq:
        _schedule_node({"thread_id": "t", "creative_assets": [_future_asset("rejected")], "status": "s"})
    enq.assert_not_called()  # compliance: a rejected post must never be scheduled/dispatched
