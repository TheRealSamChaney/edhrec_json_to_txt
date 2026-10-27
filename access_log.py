import json
import logging
import sys
import time

import streamlit as st

# One JSON object per line on stdout, so Loki can parse it with `| json`
# (`{namespace="magic"} | json | event="analysis"`). A dedicated logger with
# propagate=False keeps these lines out of Streamlit's own log formatting.
# Like metrics.py, this is a real imported module, so the handler is
# attached once per process, not once per Streamlit rerun.
_logger = logging.getLogger("edhrec.access")
_logger.setLevel(logging.INFO)
_logger.propagate = False
if not _logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("%(message)s"))
    _logger.addHandler(_handler)


def client_info():
    """Where the current session's request came from.

    Every request reaches the app through Cloudflare Tunnel -> Traefik, so
    the TCP peer is always an in-cluster pod. The real visitor is only in
    the headers Cloudflare adds at its edge.
    """
    headers = st.context.headers
    forwarded_for = headers.get("X-Forwarded-For", "")
    return {
        "client_ip": headers.get("Cf-Connecting-Ip") or forwarded_for.split(",")[0].strip() or "unknown",
        "country": headers.get("Cf-Ipcountry", "unknown"),
        "user_agent": headers.get("User-Agent", "unknown"),
    }


def log_event(event, **fields):
    _logger.info(json.dumps({"ts": time.time(), "event": event, **client_info(), **fields}))
