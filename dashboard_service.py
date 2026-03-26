"""
Real-time visualization dashboard for the Disaster Control System.

Connects to RabbitMQ via fanout exchanges (using its own exclusive queues
so it never steals messages from existing services), then pushes every
event to the browser over Server-Sent Events (SSE).

Run:
    python dashboard_service.py

Then open http://localhost:5000 in a browser.
"""

import json
import queue
import threading

import pika
from flask import Flask, Response, jsonify, render_template, request

from common import (
    INCIDENT_EXCHANGE,
    DISPATCH_EXCHANGE,
    STATUS_EXCHANGE,
    get_rabbitmq_connection,
    publish_message,
    INCIDENT_QUEUE,
)
from risk_analysis import (
    register_active_incident,
    resolve_active_incident,
    get_risk_heatmap,
    get_neighborhood_summary,
    get_incident_risk,
)

# ---------------------------------------------------------------------------
# Shared state (written by RabbitMQ thread, read by Flask threads)
# ---------------------------------------------------------------------------

units = {
    "P1": {"type": "police",    "location": [1, 2], "status": "available", "incident": None},
    "P2": {"type": "police",    "location": [4, 4], "status": "available", "incident": None},
    "P3": {"type": "police",    "location": [2, 5], "status": "available", "incident": None},
    "F1": {"type": "fire",      "location": [2, 4], "status": "available", "incident": None},
    "F2": {"type": "fire",      "location": [5, 5], "status": "available", "incident": None},
    "F3": {"type": "fire",      "location": [1, 4], "status": "available", "incident": None},
    "A1": {"type": "ambulance", "location": [5, 1], "status": "available", "incident": None},
    "A2": {"type": "ambulance", "location": [2, 1], "status": "available", "incident": None},
    "A3": {"type": "ambulance", "location": [3, 3], "status": "available", "incident": None},
}

# incident_id -> {"data": {...}, "status": "new"|"dispatched"|"resolved", "assigned_unit": ...}
incidents = {}

# ---------------------------------------------------------------------------
# SSE subscriber management
# ---------------------------------------------------------------------------

_subscribers: list[queue.Queue] = []
_sub_lock = threading.Lock()


def _broadcast(event: dict):
    """Send an event dict to every connected SSE client."""
    with _sub_lock:
        dead = []
        for q in _subscribers:
            try:
                q.put_nowait(event)
            except Exception:
                dead.append(q)
        for q in dead:
            _subscribers.remove(q)


def _subscribe() -> queue.Queue:
    q: queue.Queue = queue.Queue()
    with _sub_lock:
        _subscribers.append(q)
    return q


def _unsubscribe(q: queue.Queue):
    with _sub_lock:
        try:
            _subscribers.remove(q)
        except ValueError:
            pass

# ---------------------------------------------------------------------------
# RabbitMQ consumer (runs in a daemon thread)
# ---------------------------------------------------------------------------


def _rabbitmq_consumer():
    connection = pika.BlockingConnection(pika.ConnectionParameters(host="localhost"))
    channel = connection.channel()

    # Declare the same fanout exchanges (idempotent)
    for exch in (INCIDENT_EXCHANGE, DISPATCH_EXCHANGE, STATUS_EXCHANGE):
        channel.exchange_declare(exchange=exch, exchange_type="fanout")

    # Create exclusive auto-delete queues for the dashboard
    q_incident = channel.queue_declare(queue="", exclusive=True).method.queue
    q_dispatch = channel.queue_declare(queue="", exclusive=True).method.queue
    q_status   = channel.queue_declare(queue="", exclusive=True).method.queue

    channel.queue_bind(queue=q_incident, exchange=INCIDENT_EXCHANGE)
    channel.queue_bind(queue=q_dispatch, exchange=DISPATCH_EXCHANGE)
    channel.queue_bind(queue=q_status,   exchange=STATUS_EXCHANGE)

    # ---- callbacks ----

    def on_incident(_ch, method, _props, body):
        data = json.loads(body)
        iid = data["incident_id"]
        incidents[iid] = {"data": data, "status": "new", "assigned_unit": None}
        register_active_incident(data["location"])
        _broadcast({"type": "incident", "data": data})
        print(f"[Dashboard] Incident {iid}: {data['type']} at {data['location']} "
              f"(risk={data.get('risk_level', 'N/A')})")

    def on_dispatch(_ch, method, _props, body):
        data = json.loads(body)
        iid = data["incident_id"]
        uid = data["unit_id"]

        # Track incident
        if iid in incidents:
            incidents[iid]["status"] = "dispatched"
            incidents[iid]["assigned_unit"] = uid
        else:
            incidents[iid] = {
                "data": {
                    "incident_id": iid,
                    "type": data.get("incident_type"),
                    "location": data.get("incident_location"),
                    "risk_level": data.get("risk_level"),
                },
                "status": "dispatched",
                "assigned_unit": uid,
            }

        # Track primary unit
        if uid in units:
            units[uid]["status"] = "dispatched"
            units[uid]["incident"] = iid

        # Track additional unit for high-risk dispatch
        additional_uid = data.get("additional_unit_id")
        if additional_uid and additional_uid in units:
            units[additional_uid]["status"] = "dispatched"
            units[additional_uid]["incident"] = iid

        _broadcast({"type": "dispatch", "data": data})
        print(f"[Dashboard] Dispatch {uid} -> incident {iid}"
              + (f" (+ {additional_uid})" if additional_uid else ""))

    def on_status(_ch, method, _props, body):
        data = json.loads(body)
        uid = data["unit_id"]
        status = data["status"]

        if uid in units:
            if status == "completed":
                # Free all units involved in this dispatch
                all_ids = data.get("all_unit_ids") or [uid]
                for free_uid in all_ids:
                    if free_uid in units:
                        iid = units[free_uid].get("incident")
                        if iid and iid in incidents:
                            incidents[iid]["status"] = "resolved"
                        units[free_uid]["status"] = "available"
                        units[free_uid]["incident"] = None

                # Resolve dynamic risk
                incident_location = data.get("incident_location")
                if incident_location:
                    resolve_active_incident(incident_location)
            else:
                units[uid]["status"] = status

        _broadcast({"type": "status", "data": data})
        print(f"[Dashboard] Status {uid} -> {status}")

    channel.basic_consume(queue=q_incident, on_message_callback=on_incident, auto_ack=True)
    channel.basic_consume(queue=q_dispatch, on_message_callback=on_dispatch, auto_ack=True)
    channel.basic_consume(queue=q_status,   on_message_callback=on_status,   auto_ack=True)

    print("[Dashboard] Listening on RabbitMQ exchanges...")
    channel.start_consuming()

# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("dashboard.html")


@app.route("/state")
def state():
    """Return the current snapshot (useful for debugging / initial load)."""
    return {
        "units": units,
        "incidents": {str(k): v for k, v in incidents.items()},
    }


@app.route("/risk")
def risk():
    """Return the current risk heatmap and neighborhood summary."""
    return jsonify({
        "heatmap": get_risk_heatmap(),
        "neighborhoods": get_neighborhood_summary(),
    })


@app.route("/generate", methods=["POST"])
def generate_incident():
    """Create and publish a random incident from the dashboard."""
    import time, random
    incident_types = ["fire", "police", "ambulance"]

    data = request.get_json(silent=True) or {}
    inc_type = data.get("type") or random.choice(incident_types)
    severity = data.get("severity") or random.randint(1, 5)
    location = data.get("location") or [random.randint(0, 6), random.randint(0, 6)]

    incident = {
        "incident_id": int(time.time() * 1000),
        "type":        inc_type,
        "severity":    severity,
        "location":    location,
        "risk_level":  get_incident_risk(location, severity),
        "timestamp":   time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    connection, channel = get_rabbitmq_connection()
    try:
        publish_message(channel, INCIDENT_QUEUE, incident)
    finally:
        connection.close()

    return jsonify(incident), 201


@app.route("/events")
def events():
    """SSE stream — pushes every RabbitMQ event to the browser."""
    q = _subscribe()

    def generate():
        # Send full state as the first event so the client is up to date
        init = {
            "type": "init",
            "units": units,
            "incidents": {str(k): v for k, v in incidents.items()},
            "heatmap": get_risk_heatmap(),
            "neighborhoods": get_neighborhood_summary(),
        }
        yield f"data: {json.dumps(init)}\n\n"
        try:
            while True:
                try:
                    event = q.get(timeout=25)
                    # Ensure incident_id keys are strings for JSON
                    yield f"data: {json.dumps(event, default=str)}\n\n"
                except queue.Empty:
                    yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
        finally:
            _unsubscribe(q)

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Start RabbitMQ consumer in a daemon thread
    t = threading.Thread(target=_rabbitmq_consumer, daemon=True)
    t.start()

    print("[Dashboard] Starting Flask on http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, threaded=True)
