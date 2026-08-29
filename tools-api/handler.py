import json
from pathlib import Path
from typing import Any


FIXTURES = json.loads(Path(__file__).with_name("fixtures.json").read_text())


def _response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Cache-Control": "no-store",
        },
        "body": json.dumps(body, ensure_ascii=False),
    }


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    resource = event.get("resource", "")
    params = event.get("pathParameters") or {}

    if resource == "/orders/{orderId}":
        collection = "orders"
        key = params.get("orderId")
    elif resource == "/shipments/{orderId}":
        collection = "shipments"
        key = params.get("orderId")
    elif resource == "/inventory/{sku}":
        collection = "inventory"
        key = params.get("sku")
    else:
        return _response(404, {"error": "unsupported route"})

    item = FIXTURES[collection].get(key)
    if item is None:
        return _response(
            404,
            {
                "error": "not found",
                "source": collection,
                "lookupKey": key,
            },
        )

    return _response(
        200,
        {
            "source": collection,
            "data": item,
        },
    )

