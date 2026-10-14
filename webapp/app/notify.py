from typing import Optional

import requests


def send_webhook(url: str, message: str) -> Optional[str]:
    """POSTs the message to the webhook. Returns None on success (or when no URL is set),
    otherwise a short error description.

    The error deliberately never contains the URL: webhook URLs carry a secret
    token, and requests' own exception text includes the full URL.

    Sends both "content" (Discord) and "text" (Slack, Mattermost, Rocket.Chat) so
    those webhooks work as-is. Receivers ignore the key they don't use.
    """
    if not url:
        return None
    try:
        response = requests.post(url, json={"content": message, "text": message}, timeout=5)
    except requests.RequestException as e:
        return type(e).__name__
    if not response.ok:
        return f"HTTP {response.status_code}"
    return None
