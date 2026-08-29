import importlib.util
import json
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "tools-api" / "handler.py"
SPEC = importlib.util.spec_from_file_location("tools_handler", MODULE_PATH)
assert SPEC and SPEC.loader
HANDLER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HANDLER)


class HandlerTest(unittest.TestCase):
    def invoke(self, resource: str, params: dict[str, str]):
        response = HANDLER.handler(
            {
                "resource": resource,
                "pathParameters": params,
            },
            None,
        )
        return response["statusCode"], json.loads(response["body"])

    def test_order_status(self):
        status, body = self.invoke(
            "/orders/{orderId}",
            {"orderId": "A-100"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["source"], "orders")
        self.assertEqual(body["data"]["status"], "PROCESSING")

    def test_shipment_fixture_conflicts_plausibly_with_order(self):
        status, body = self.invoke(
            "/shipments/{orderId}",
            {"orderId": "A-100"},
        )
        self.assertEqual(status, 200)
        self.assertEqual(body["source"], "shipments")
        self.assertEqual(body["data"]["status"], "DELIVERED")

    def test_missing_item(self):
        status, body = self.invoke(
            "/inventory/{sku}",
            {"sku": "UNKNOWN"},
        )
        self.assertEqual(status, 404)
        self.assertEqual(body["error"], "not found")


if __name__ == "__main__":
    unittest.main()

