import threading
from prometheus_client import Counter, Histogram, start_http_server

ANALYSES_STARTED = Counter("edhrec_analyses_started_total", "Total deck analyses started")
ANALYSES_COMPLETED = Counter("edhrec_analyses_completed_total", "Total deck analyses completed successfully")
ANALYSES_FAILED = Counter("edhrec_analyses_failed_total", "Total deck analyses failed")
ANALYSIS_DURATION = Histogram(
    "edhrec_analysis_duration_seconds",
    "End-to-end analysis duration in seconds",
    buckets=[1, 5, 10, 30, 60, 120, 300],
)
# outcome: success | not_found | no_decks | error. not_found/no_decks end
# the run via st.stop(), which raises a BaseException rather than an
# Exception, so they never reach ANALYSES_COMPLETED or ANALYSES_FAILED.
ANALYSIS_OUTCOMES = Counter("edhrec_analysis_outcomes_total", "Deck analyses by outcome", ["outcome"])
# Only incremented on success, so every label value is a commander EDHRec
# actually knows about -- never raw user input (keeps cardinality bounded).
COMMANDER_ANALYSES = Counter(
    "edhrec_commander_analyses_total", "Successful deck analyses per commander", ["commander"]
)
SESSIONS_STARTED = Counter("edhrec_sessions_started_total", "Browser sessions started")


def _start_server():
    try:
        start_http_server(8502)
    except OSError:
        pass  # already started by a previous import


threading.Thread(target=_start_server, daemon=True).start()
