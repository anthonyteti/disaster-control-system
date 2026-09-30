"""Tests of production service functions; no running RabbitMQ required."""
import unittest
from unittest.mock import Mock, patch

import dispatch_service as dispatch
import status_listener
from common import STATUS_EXCHANGE, STATUS_QUEUE


class ServiceTests(unittest.TestCase):
    def test_status_listener_uses_its_own_fanout_subscription(self):
        channel = Mock()
        channel.queue_declare.return_value.method.queue = "listener-generated-queue"
        with patch.object(status_listener, "get_rabbitmq_connection", return_value=(Mock(), channel)):
            status_listener.main()
        channel.queue_declare.assert_called_once_with(queue="", exclusive=True)
        channel.queue_bind.assert_called_once_with(exchange=STATUS_EXCHANGE, queue="listener-generated-queue")
        subscription = channel.basic_consume.call_args.kwargs
        self.assertEqual(subscription["queue"], "listener-generated-queue")
        self.assertNotEqual(subscription["queue"], STATUS_QUEUE)

    def test_critical_dispatch_selects_nearest_eligible_unit(self):
        units = [
            dict(unit_id="busy", unit_type="fire", location=[0, 0], status="busy"),
            dict(unit_id="wrong", unit_type="police", location=[0, 0], status="available"),
            dict(unit_id="far", unit_type="fire", location=[6, 6], status="available"),
            dict(unit_id="near", unit_type="fire", location=[1, 0], status="available"),
        ]
        with patch.object(dispatch, "units", units):
            self.assertIs(dispatch.find_best_unit("fire", [0, 0], severity=5), units[3])
            self.assertIsNone(dispatch.find_best_unit("ambulance", [0, 0]))


if __name__ == "__main__":
    unittest.main()
