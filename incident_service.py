from datetime import datetime
import sys
import time
import random

from common import INCIDENT_QUEUE, get_rabbitmq_connection, publish_message
from risk_analysis import get_incident_risk

# Counter to avoid incident_id collisions within the same second
_incident_counter = 0


def create_sample_incident():
    """
    Create a sample disaster incident with a unique ID,
    random type, severity, and location on a 7x7 grid.
    """
    global _incident_counter
    _incident_counter += 1

    incident_types = ["fire", "police", "ambulance"]
    location = [random.randint(0, 6), random.randint(0, 6)]
    severity = random.randint(1, 5)
    return {
        "incident_id": int(time.time() * 1000) + _incident_counter,
        "type":        random.choice(incident_types),
        "severity":    severity,
        "location":    location,
        "risk_level":  get_incident_risk(location, severity),
        "timestamp":   datetime.now().isoformat(),
    }


def create_incident(incident_type, location, description, severity):
    """Create and publish a specific incident programmatically."""
    global _incident_counter
    _incident_counter += 1

    incident = {
        "incident_id": int(time.time() * 1000) + _incident_counter,
        "type":        incident_type,
        "location":    location,
        "description": description,
        "severity":    severity,
        "risk_level":  get_incident_risk(location, severity),
    }
    connection, channel = get_rabbitmq_connection()
    try:
        publish_message(channel, INCIDENT_QUEUE, incident)
        print(f"[Incident Service] Created incident with risk level: {incident['risk_level']}")
    finally:
        connection.close()
    return incident


def main():
    loop_mode = "--loop" in sys.argv

    if loop_mode:
        # Parse optional interval: --loop 5  (defaults to 5 seconds)
        interval = 5
        idx = sys.argv.index("--loop")
        if idx + 1 < len(sys.argv):
            try:
                interval = int(sys.argv[idx + 1])
            except ValueError:
                pass

        print(f"[Incident Service] Continuous mode — generating an incident every {interval}s")
        print("[Incident Service] Press Ctrl+C to stop.\n")

        connection, channel = get_rabbitmq_connection()
        try:
            while True:
                incident = create_sample_incident()
                publish_message(channel, INCIDENT_QUEUE, incident)
                print(f"[Incident Service] Published: {incident['type']} sev={incident['severity']} "
                      f"at {incident['location']} risk={incident['risk_level']}")
                time.sleep(interval)
        except KeyboardInterrupt:
            print("\n[Incident Service] Stopped.")
        finally:
            connection.close()
    else:
        # Single-shot mode
        connection, channel = get_rabbitmq_connection()
        try:
            incident = create_sample_incident()
            print(f"[Incident Service] Created incident: {incident}")
            publish_message(channel, INCIDENT_QUEUE, incident)
            print("[Incident Service] Incident published successfully.")
        finally:
            connection.close()


if __name__ == "__main__":
    main()
