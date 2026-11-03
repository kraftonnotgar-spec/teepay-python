"""Every public OpenAPI operation must be reachable through the SDK."""

from __future__ import annotations

import inspect
import json
import os
import re
from pathlib import Path
from typing import Any, Callable, Dict, Tuple

import pytest

from teepay import AsyncTeePay, TeePay

from .conftest import FIXTURES, FIXTURES_DIR

SPEC = json.loads((FIXTURES_DIR / "openapi.public.json").read_text(encoding="utf-8"))
UUID = "7c0e5d2a-1b3f-4c8e-9a6d-2f4b8e1c0d9a"

# operationId -> (SDK method path, sample call)
OPERATIONS: Dict[str, Tuple[str, Callable[[Any], Any]]] = {
    "get-api-key": ("whoami", lambda c: c.whoami()),
    "get-capabilities": ("capabilities", lambda c: c.capabilities()),
    "create-collection": (
        "collections.create",
        lambda c: c.collections.create(money={"amount_minor": "500000", "currency": "TZS"}, customer={"country": "TZ", "phone": "+255712345678"}),
    ),
    "list-collections": ("collections.list", lambda c: c.collections.list(limit=10)),
    "get-collection": ("collections.retrieve", lambda c: c.collections.retrieve("TP8K2M4QZ1")),
    "create-payout-quote": (
        "disbursements.quote",
        lambda c: c.disbursements.quote(money={"amount": 2500000, "currency": "TZS"}, destination={"channel": "mobile", "name": "Juma Ali", "phone": "255712345678"}, narration="x"),
    ),
    "create-payout": ("disbursements.create", lambda c: c.disbursements.create(quote_id="q_4f2c8a1b", idempotency_key="payout-0001")),
    "list-payouts": ("disbursements.list", lambda c: c.disbursements.list()),
    "get-payout": ("disbursements.retrieve", lambda c: c.disbursements.retrieve("TPPO7Q2X9D")),
    "create-control-number": ("control_numbers.create", lambda c: c.control_numbers.create(kind="bill", customer={"name": "A"}, amount_minor="5000000")),
    "list-control-numbers": ("control_numbers.list", lambda c: c.control_numbers.list()),
    "get-control-number": ("control_numbers.retrieve", lambda c: c.control_numbers.retrieve("22222222-2222-4222-8222-222222222222")),
    "create-checkout-session": ("checkout_sessions.create", lambda c: c.checkout_sessions.create(title="Order", amount_minor="500000", currency="TZS")),
    "list-checkout-sessions": ("checkout_sessions.list", lambda c: c.checkout_sessions.list(limit=5)),
    "get-checkout-session": ("checkout_sessions.retrieve", lambda c: c.checkout_sessions.retrieve(UUID)),
}

HEADER_KEYED = {"create-collection", "create-control-number", "create-checkout-session"}


def spec_operations(spec: Dict[str, Any]) -> Dict[str, Tuple[str, str]]:
    ops = {}
    for path, methods in spec["paths"].items():
        for method, op in methods.items():
            if method in ("get", "post", "put", "patch", "delete"):
                ops[op["operationId"]] = (method.upper(), path)
    return ops


SPEC_OPS = spec_operations(SPEC)


def test_spec_is_public_only():
    assert SPEC_OPS, "no operations in vendored spec"
    for _, path in SPEC_OPS.values():
        assert path.startswith("/v1/"), path
    text = json.dumps(SPEC).lower()
    for word in ("karpy", "gokar", "/api/integrations", "servicehmac", "x-gokar"):
        assert word not in text


def test_every_operation_is_mapped():
    assert set(OPERATIONS) == set(SPEC_OPS)
    assert set(FIXTURES["operations"]) == set(SPEC_OPS)


def _resolve(obj: Any, dotted: str) -> Any:
    for part in dotted.split("."):
        obj = getattr(obj, part)
    return obj


@pytest.mark.parametrize("op_id", sorted(SPEC_OPS))
def test_methods_exist_on_both_clients(op_id):
    name, _ = OPERATIONS[op_id]
    sync = TeePay("tp_test_x")
    asyn = AsyncTeePay("tp_test_x")
    assert callable(_resolve(sync, name))
    assert inspect.iscoroutinefunction(_resolve(asyn, name))


def _matches(template: str, path: str) -> bool:
    return re.fullmatch(re.sub(r"\{[^}]+\}", r"[^/]+", template), path) is not None


@pytest.mark.parametrize("op_id", sorted(SPEC_OPS))
def test_operation_hits_spec_route(op_id, client, server):
    method, template = SPEC_OPS[op_id]
    _, call = OPERATIONS[op_id]
    result = call(client)
    req = server.last
    assert req["method"] == method
    assert _matches(template, req["path"]), (template, req["path"])
    assert result.last_response.status == FIXTURES["operations"][op_id]["status"]
    op = SPEC["paths"][template][method.lower()]
    header_params = [p["name"] for p in op.get("parameters", []) if p.get("in") == "header"]
    if "Idempotency-Key" in header_params:
        assert op_id in HEADER_KEYED
        key = req["headers"]["idempotency-key"]
        param = next(p for p in op["parameters"] if p["name"] == "Idempotency-Key")
        assert re.fullmatch(param["schema"].get("pattern", ".*"), key)
        assert param["schema"]["minLength"] <= len(key) <= param["schema"]["maxLength"]
    else:
        assert "idempotency-key" not in req["headers"]
    query_names = {p["name"] for p in op.get("parameters", []) if p.get("in") == "query"}
    assert set(req["query"]) <= query_names
    body_schema = op.get("requestBody", {}).get("content", {}).get("application/json", {}).get("schema")
    if body_schema:
        _check_body(body_schema, req["body"])
    else:
        assert req["body"] is None


def _check_body(schema: Dict[str, Any], value: Any) -> None:
    """Minimal JSON-schema check for request bodies the SDK produced."""
    if "oneOf" in schema:
        errors = []
        for option in schema["oneOf"]:
            try:
                _check_body(option, value)
                return
            except AssertionError as exc:
                errors.append(exc)
        raise AssertionError(errors)
    if "const" in schema:
        assert value == schema["const"]
    if "enum" in schema:
        assert value in schema["enum"]
    kind = schema.get("type")
    if kind == "object" or "properties" in schema:
        assert isinstance(value, dict)
        for name in schema.get("required", []):
            assert name in value, name
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            assert set(value) <= set(props), set(value) - set(props)
        for name, item in value.items():
            if name in props:
                _check_body(props[name], item)
    elif kind == "string":
        assert isinstance(value, str)
        if "pattern" in schema:
            assert re.search(schema["pattern"], value), (schema["pattern"], value)
    elif kind == "integer":
        assert isinstance(value, int) and not isinstance(value, bool)


def _resolve_ref(ref: str) -> Dict[str, Any]:
    node: Any = SPEC
    for part in ref.lstrip("#/").split("/"):
        node = node[part]
    return node  # type: ignore[no-any-return]


def _check_response(schema: Dict[str, Any], value: Any, where: str) -> None:
    if "$ref" in schema:
        if not schema["$ref"].startswith("#"):
            return
        schema = _resolve_ref(schema["$ref"])
    kind = schema.get("type")
    kinds = kind if isinstance(kind, list) else [kind]
    if value is None:
        assert "null" in kinds or kind is None, where
        return
    if "const" in schema:
        assert value == schema["const"], where
    if "enum" in schema:
        assert value in schema["enum"], where
    if "object" in kinds or "properties" in schema:
        assert isinstance(value, dict), where
        for name in schema.get("required", []):
            assert name in value, f"{where}.{name} missing"
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            assert set(value) <= set(props), f"{where}: unexpected {set(value) - set(props)}"
        for name, item in value.items():
            if name in props:
                _check_response(props[name], item, f"{where}.{name}")
    if "array" in kinds:
        assert isinstance(value, list), where
        for i, item in enumerate(value):
            _check_response(schema.get("items", {}), item, f"{where}[{i}]")
    if kinds == ["string"] and "pattern" in schema:
        assert re.search(schema["pattern"], value), where
    if kinds == ["integer"]:
        assert isinstance(value, int), where


@pytest.mark.parametrize("op_id", sorted(SPEC_OPS))
def test_fixture_matches_response_schema(op_id):
    method, template = SPEC_OPS[op_id]
    fixture = FIXTURES["operations"][op_id]
    assert (fixture["method"], fixture["path"]) == (method, template)
    responses = SPEC["paths"][template][method.lower()]["responses"]
    assert str(fixture["status"]) in responses, (op_id, fixture["status"])
    schema = responses[str(fixture["status"])].get("content", {}).get("application/json", {}).get("schema")
    if schema:
        _check_response(schema, fixture["body"], op_id)


def _upstream_spec() -> Path:
    env = os.environ.get("TEEPAY_OPENAPI")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2].parent / "teepay" / "docs-site" / "openapi" / "teepay.json"


@pytest.mark.skipif(not _upstream_spec().exists(), reason="published TeePay OpenAPI not available")
def test_vendored_spec_matches_published_spec():
    upstream = json.loads(_upstream_spec().read_text(encoding="utf-8"))
    assert spec_operations(upstream) == SPEC_OPS
