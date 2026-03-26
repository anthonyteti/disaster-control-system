import json
import pika

# Queue names
INCIDENT_QUEUE = "incident_queue"
DISPATCH_QUEUE = "dispatch_queue"
STATUS_QUEUE = "status_queue"

# Fanout exchanges — each queue gets its own exchange so multiple
# consumers (services + dashboard) can receive the same messages.
INCIDENT_EXCHANGE = "incident_exchange"
DISPATCH_EXCHANGE = "dispatch_exchange"
STATUS_EXCHANGE = "status_exchange"

QUEUE_EXCHANGE_MAP = {
    INCIDENT_QUEUE: INCIDENT_EXCHANGE,
    DISPATCH_QUEUE: DISPATCH_EXCHANGE,
    STATUS_QUEUE: STATUS_EXCHANGE,
}


def get_rabbitmq_connection():
    """
    Create and return a RabbitMQ connection and channel.
    """
    connection = pika.BlockingConnection(
        pika.ConnectionParameters(host="localhost")
    )
    channel = connection.channel()

    # Declare fanout exchanges and bind each queue to its exchange
    for queue_name, exchange_name in QUEUE_EXCHANGE_MAP.items():
        channel.exchange_declare(exchange=exchange_name, exchange_type="fanout")
        channel.queue_declare(queue=queue_name)
        channel.queue_bind(queue=queue_name, exchange=exchange_name)

    return connection, channel


def publish_message(channel, queue_name, message):
    """
    Publish a JSON message through the fanout exchange for the given queue.
    """
    exchange = QUEUE_EXCHANGE_MAP.get(queue_name, "")
    channel.basic_publish(
        exchange=exchange,
        routing_key="",
        body=json.dumps(message)
    )
    print(f"[Sent] Queue={queue_name}, Message={message}")



