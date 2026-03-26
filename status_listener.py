import json

from common import STATUS_QUEUE, get_rabbitmq_connection


def callback(ch, method, properties, body):
    status_update = json.loads(body)
    print(f"[Status Listener] Received status update: {status_update}")


def main():
    connection, channel = get_rabbitmq_connection()

    channel.basic_consume(
        queue=STATUS_QUEUE,
        on_message_callback=callback,
        auto_ack=True
    )

    print("[Status Listener] Waiting for status updates...")
    channel.start_consuming()


if __name__ == "__main__":
    main()


