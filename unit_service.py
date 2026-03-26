import json
import time

from common import (
    DISPATCH_QUEUE,
    STATUS_QUEUE,
    get_rabbitmq_connection,
    publish_message
)


def handle_assignment(channel, assignment):
    unit_id           = assignment["unit_id"]
    incident_id       = assignment["incident_id"]
    all_unit_ids      = assignment.get("all_unit_ids", [unit_id])
    incident_location = assignment.get("incident_location")

    print(f"[Unit Service] Unit {unit_id} assigned to incident {incident_id}")

    for status in ("en_route", "on_scene", "completed"):
        status_update = {
            "unit_id":           unit_id,
            "incident_id":       incident_id,
            "status":            status,
            "all_unit_ids":      all_unit_ids,
            "incident_location": incident_location,
        }
        publish_message(channel, STATUS_QUEUE, status_update)
        if status != "completed":
            time.sleep(2)

    print(f"[Unit Service] Unit {unit_id} completed incident {incident_id}")


def callback(ch, method, properties, body):
    assignment = json.loads(body)
    handle_assignment(ch, assignment)


def main():
    connection, channel = get_rabbitmq_connection()

    channel.basic_consume(
        queue=DISPATCH_QUEUE,
        on_message_callback=callback,
        auto_ack=True
    )

    print("[Unit Service] Waiting for dispatch assignments...")
    channel.start_consuming()


if __name__ == "__main__":
    main()
