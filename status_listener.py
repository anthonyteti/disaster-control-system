import json

from common import STATUS_EXCHANGE, get_rabbitmq_connection


def callback(ch, method, properties, body):
    status_update = json.loads(body)
    print(f"[Status Listener] Received status update: {status_update}")


def main():
    connection, channel = get_rabbitmq_connection()

    # A separate fanout subscription observes events without taking the
    # dispatcher's completion messages from its work queue.
    result = channel.queue_declare(queue="", exclusive=True)
    listener_queue = result.method.queue
    channel.queue_bind(exchange=STATUS_EXCHANGE, queue=listener_queue)

    channel.basic_consume(
        queue=listener_queue,
        on_message_callback=callback,
        auto_ack=True
    )

    print("[Status Listener] Waiting for status updates...")
    channel.start_consuming()


if __name__ == "__main__":
    main()


