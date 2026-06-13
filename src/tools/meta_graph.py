"""
Meta Graph API tool layer — Phase 2.

Design rules:
- One job per tool; typed inputs and outputs.
- Every failure returns a MetaError with a `recovery` hint the agent can act on.
- Exposed as an MCP server via Composio; register in Claude Code with /mcp.
- Tool distribution: publishing tools → Publishing node only;
  comment/DM tools → Engagement node only.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum


class MetaErrorCode(str, Enum):
    RATE_LIMITED = "RATE_LIMITED"
    PAGE_PUBLISH_AUTH_REQUIRED = "PAGE_PUBLISH_AUTH_REQUIRED"
    DM_WINDOW_EXPIRED = "DM_WINDOW_EXPIRED"
    AUDIO_UNAVAILABLE = "AUDIO_UNAVAILABLE"


@dataclass
class MetaError:
    code: MetaErrorCode
    message: str
    recovery: str  # agent-readable action: "retry_after_60s", "route_to_manual_queue", etc.


# --- Publishing tools (Publishing node only) ---

def create_media_container(image_url: str, caption: str) -> dict | MetaError:
    """Step 1 of the two-step container-publish model."""
    raise NotImplementedError  # Phase 2


def poll_container_status(container_id: str) -> dict | MetaError:
    """Poll until status is FINISHED or ERROR."""
    raise NotImplementedError  # Phase 2


def publish_media(container_id: str) -> dict | MetaError:
    """Step 2: publish a FINISHED container."""
    raise NotImplementedError  # Phase 2


# --- Engagement tools (Engagement node only) ---

def reply_to_comment(comment_id: str, message: str) -> dict | MetaError:
    raise NotImplementedError  # Phase 2


def send_dm_reply(thread_id: str, message: str) -> dict | MetaError:
    """Only valid within the 24-hr user-initiated window."""
    raise NotImplementedError  # Phase 2


# --- Analytics tools (Analytics node only) ---

def get_media_insights(media_id: str) -> dict | MetaError:
    raise NotImplementedError  # Phase 2
