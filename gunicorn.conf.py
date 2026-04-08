"""Gunicorn configuration for doda-tracker."""

workers = 1


def post_fork(server, worker):
    """Start the background SAT checker in the worker process after forking.

    With gunicorn's pre-fork model, threads started before fork do not survive
    into worker processes. This hook runs inside each worker after the fork,
    so the background thread is guaranteed to be alive in the right process.
    """
    try:
        import app as _app
        _app._start_background(_app._cfg)
        server.log.info("Background checker started (worker pid=%s)", worker.pid)
    except Exception as exc:
        server.log.error("Failed to start background checker: %s", exc)
