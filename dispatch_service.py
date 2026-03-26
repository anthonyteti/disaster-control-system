import json
import threading

from common import (
    INCIDENT_QUEUE,
    DISPATCH_QUEUE,
    STATUS_QUEUE,
    get_rabbitmq_connection,
    publish_message,
)
from risk_analysis import (
    register_active_incident,
    resolve_active_incident,
    get_relocation_suggestions,
    get_neighborhood_summary,
    get_neighborhood_risk,
)

# Composite scoring weights
DISTANCE_WEIGHT = 0.6
SEVERITY_WEIGHT = 0.4
MAX_GRID_DISTANCE = 12   # max Manhattan distance on a 7x7 grid (0,0)->(6,6)

# Simulated emergency units
units = [
    {"unit_id": "P1", "unit_type": "police",    "location": [1, 2], "status": "available"},
    {"unit_id": "P2", "unit_type": "police",    "location": [4, 4], "status": "available"},
    {"unit_id": "P3", "unit_type": "police",    "location": [2, 5], "status": "available"},
    {"unit_id": "F1", "unit_type": "fire",      "location": [2, 4], "status": "available"},
    {"unit_id": "F2", "unit_type": "fire",      "location": [5, 5], "status": "available"},
    {"unit_id": "F3", "unit_type": "fire",      "location": [1, 4], "status": "available"},
    {"unit_id": "A1", "unit_type": "ambulance", "location": [5, 1], "status": "available"},
    {"unit_id": "A2", "unit_type": "ambulance", "location": [2, 1], "status": "available"},
    {"unit_id": "A3", "unit_type": "ambulance", "location": [3, 3], "status": "available"},
]

_units_lock = threading.Lock()


def print_unit_status():
    print("\n[Dispatch Service] Current Unit Status:")
    for unit in units:
        print(
            f"  {unit['unit_id']} ({unit['unit_type']}) - "
            f"Location: {unit['location']} - Status: {unit['status']}"
        )
    print()


def print_neighborhood_summary():
    print("\n[Dispatch Service] Neighborhood Risk Summary:")
    for nb in get_neighborhood_summary():
        print(
            f"  {nb['neighborhood']:<14} base={nb['base_risk']}  "
            f"historical={nb['historical_incidents']}  "
            f"active={nb['active_incidents']}  "
            f"effective={nb['effective_risk']}"
        )
    print()


def manhattan_distance(loc1, loc2):
    return abs(loc1[0] - loc2[0]) + abs(loc1[1] - loc2[1])


def find_best_unit(incident_type, incident_location, severity=3):
    """
    Composite scoring: weighs distance AND severity together.

    For each candidate unit the function computes:
        score = w_dist * norm_distance + w_sev * opportunity_cost

    opportunity_cost = zone_risk * (1 - norm_severity)
      - Units stationed in high-risk zones are valuable sentinels.
      - Sending them to a low-severity incident wastes that positioning.
      - For critical incidents (severity=5) the opportunity term drops
        to zero and pure proximity decides.

    This ensures critical emergencies receive the fastest response while
    low-severity incidents avoid pulling units away from dangerous areas.
    """
    matching = [
        u for u in units
        if u["unit_type"] == incident_type and u["status"] == "available"
    ]
    if not matching:
        return None

    severity_norm = max(1, min(severity, 5)) / 5.0   # 0.2 – 1.0

    def composite_score(unit):
        dist = manhattan_distance(unit["location"], incident_location)
        norm_dist = dist / MAX_GRID_DISTANCE

        # Opportunity cost: how valuable is this unit's current position?
        zone_risk = get_neighborhood_risk(unit["location"])
        opportunity = zone_risk * (1 - severity_norm)

        return DISTANCE_WEIGHT * norm_dist + SEVERITY_WEIGHT * opportunity

    return min(matching, key=composite_score)


def apply_relocation_suggestions():
    suggestions = get_relocation_suggestions(units)
    if not suggestions:
        return
    print("\n[Dispatch Service] Proactive Relocation Suggestions:")
    for s in suggestions:
        print(
            f"  Move {s['unit_id']} ({s['unit_type']}) from {s['current_location']} "
            f"-> {s['suggested_location']} | {s['reason']}"
        )
        for unit in units:
            if unit["unit_id"] == s["unit_id"] and unit["status"] == "available":
                unit["location"] = s["suggested_location"]
                break
    print()


def handle_incident(channel, incident):
    print(f"[Dispatch Service] Received incident: {incident}")
    risk_level        = incident.get("risk_level", 0)
    incident_type     = incident["type"]
    incident_location = incident["location"]
    print(f"[Dispatch Service] Incident risk level: {risk_level}")

    severity = incident.get("severity", 3)

    register_active_incident(incident_location)

    with _units_lock:
        best_unit = find_best_unit(incident_type, incident_location, severity)
        if best_unit is None:
            print(f"[Dispatch Service] No available unit for incident {incident['incident_id']}")
            print_unit_status()
            return

        best_unit["status"] = "busy"
        all_unit_ids = [best_unit["unit_id"]]

        assignment = {
            "incident_id":        incident["incident_id"],
            "incident_type":      incident_type,
            "incident_location":  incident_location,
            "unit_id":            best_unit["unit_id"],
            "unit_type":          best_unit["unit_type"],
            "risk_level":         risk_level,
            "all_unit_ids":       all_unit_ids,
        }

        # High-risk incidents get an additional unit
        if risk_level > 0.7:
            additional = find_best_unit(incident_type, incident_location, severity)
            if additional:
                additional["status"] = "busy"
                all_unit_ids.append(additional["unit_id"])
                assignment["additional_unit_id"]  = additional["unit_id"]
                assignment["additional_unit_type"] = additional["unit_type"]
                print(
                    f"[Dispatch Service] Assigned additional {additional['unit_id']} "
                    f"to high-risk incident {incident['incident_id']}"
                )

        apply_relocation_suggestions()

    publish_message(channel, DISPATCH_QUEUE, assignment)
    print(f"[Dispatch Service] Assigned {best_unit['unit_id']} to incident {incident['incident_id']}")
    print_neighborhood_summary()
    print_unit_status()


def handle_status_update(status_update):
    print(f"[Dispatch Service] Received status update: {status_update}")

    if status_update["status"] == "completed":
        incident_location = status_update.get("incident_location")
        if incident_location:
            resolve_active_incident(incident_location)

        unit_ids_to_free = status_update.get("all_unit_ids") or [status_update["unit_id"]]
        with _units_lock:
            for unit in units:
                if unit["unit_id"] in unit_ids_to_free:
                    unit["status"] = "available"
                    print(f"[Dispatch Service] Unit {unit['unit_id']} is now available again")

            apply_relocation_suggestions()

        print_neighborhood_summary()
        print_unit_status()


def incident_callback(ch, method, properties, body):
    handle_incident(ch, json.loads(body))


def status_callback(ch, method, properties, body):
    handle_status_update(json.loads(body))


def start_incident_consumer():
    connection, channel = get_rabbitmq_connection()
    channel.basic_consume(
        queue=INCIDENT_QUEUE,
        on_message_callback=incident_callback,
        auto_ack=True
    )
    print("[Dispatch Service] Waiting for incidents...")
    channel.start_consuming()


def start_status_consumer():
    connection, channel = get_rabbitmq_connection()
    channel.basic_consume(
        queue=STATUS_QUEUE,
        on_message_callback=status_callback,
        auto_ack=True
    )
    print("[Dispatch Service] Waiting for status updates...")
    channel.start_consuming()


def main():
    print("[Dispatch Service] Starting up...")
    print_neighborhood_summary()

    incident_thread = threading.Thread(target=start_incident_consumer, daemon=True)
    status_thread   = threading.Thread(target=start_status_consumer,   daemon=True)

    incident_thread.start()
    status_thread.start()

    incident_thread.join()
    status_thread.join()


if __name__ == "__main__":
    main()
