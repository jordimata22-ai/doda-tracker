"""
Headless replacements for the old tkinter GUI prompts.

In cloud / server deployments there is no display, so all interactive
dialogs are replaced with logging stubs:
  - prompt_order_number  → returns None  (caller must handle gracefully)
  - notify               → logs the message
  - confirm              → auto-confirms (returns True)

For local desktop use the folder-watcher path is largely superseded by
the web /upload endpoint, which collects the order number from the form.
"""

import logging

logger = logging.getLogger(__name__)


def prompt_order_number(title: str, message: str) -> str | None:
    """Headless stub — cannot interactively prompt in a server environment."""
    logger.info("prompt_order_number called (headless mode) — returning None. title=%s", title)
    return None


def notify(title: str, message: str) -> None:
    """Headless stub — logs the notification instead of showing a popup."""
    logger.info("NOTIFY [%s]: %s", title, message)


def confirm(title: str, message: str) -> bool:
    """Headless stub — auto-confirms (returns True) in a server environment."""
    logger.info("CONFIRM [%s]: %s (auto-yes in headless mode)", title, message)
    return True
