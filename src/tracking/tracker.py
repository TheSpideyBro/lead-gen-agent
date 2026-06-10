# AGENT_OWNER: analytics-001
# TASK_ID: 3af35379-03e4-4cf8-9536-263456dac75b
import os

# 1x1 transparent GIF (smallest valid tracking pixel)
PIXEL_GIF = bytes.fromhex(
    "47494638396101000100800000000000ffffff21f90401000000002c00000000"
    "010001000002024401003b"
)


def get_base_url() -> str:
    return os.getenv("TRACKING_BASE_URL", "http://localhost:8080").rstrip("/")


def tracking_url(lead_id: int, sequence_id: int) -> str:
    """Build the unique tracking-pixel URL for a given lead + sequence step."""
    return f"{get_base_url()}/track/{lead_id}/{sequence_id}.png"


def tracking_pixel_html(lead_id: int, sequence_id: int) -> str:
    """Return an <img> tag pointing at the tracking pixel, for email bodies."""
    url = tracking_url(lead_id, sequence_id)
    return (
        f'<img src="{url}" width="1" height="1" '
        f'alt="" style="display:none;border:0;width:1px;height:1px" />'
    )
