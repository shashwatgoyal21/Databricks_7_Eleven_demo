"""Calls the notebooks and the app make into the Databricks SDK must match the SDK's real signatures:
required arguments present, no unknown keyword arguments, methods that exist. Catches errors like
EndpointCoreConfigInput() missing 'name' (the second serving failure) without a workspace."""

import ast
import importlib
import inspect
from pathlib import Path

import pytest
from databricks.sdk import WorkspaceClient

ROOT = Path(__file__).resolve().parents[1]
FILES = sorted((ROOT / "src").glob("*.py")) + sorted((ROOT / "app").glob("*.py"))
SERVICES = {name for name, v in inspect.getmembers(WorkspaceClient) if isinstance(v, property)}


def _imported_sdk_names(tree):
    names = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("databricks.sdk"):
            mod = importlib.import_module(node.module)
            for a in node.names:
                names[a.asname or a.name] = getattr(mod, a.name)
    return names


def _service_class(name):
    return inspect.signature(getattr(WorkspaceClient, name).fget).return_annotation


def _check_bind(fn, call, where):
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError):
        return
    if any(isinstance(a, ast.Starred) for a in call.args) or any(k.arg is None for k in call.keywords):
        return
    try:
        sig.bind(*([None] * len(call.args)), **{k.arg: None for k in call.keywords})
    except TypeError as e:
        pytest.fail(f"{where}: {getattr(fn, '__qualname__', fn)}(...) does not match the SDK: {e}")


def _calls():
    for path in FILES:
        tree = ast.parse(path.read_text())
        sdk_names = _imported_sdk_names(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                yield path, node, sdk_names


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_sdk_constructors_and_methods_match(path):
    tree = ast.parse(path.read_text())
    sdk_names = _imported_sdk_names(tree)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        where = f"{path.name}:{node.lineno}"
        f = node.func
        if isinstance(f, ast.Name) and f.id in sdk_names and inspect.isclass(sdk_names[f.id]):
            _check_bind(sdk_names[f.id], node, where)
        # <client>.<service>.<method>(...), e.g. w.serving_endpoints.create_and_wait(...)
        if (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Attribute)
                and f.value.attr in SERVICES and f.value.attr not in {"config", "api_client"}):
            cls = _service_class(f.value.attr)
            if not inspect.isclass(cls):
                continue
            assert hasattr(cls, f.attr), f"{where}: {cls.__name__} has no method {f.attr}"
            _check_bind(getattr(cls(None), f.attr), node, where)


def test_feature_store_model_is_logged_with_output_schema():
    """Unity Catalog needs an output schema; fe.log_model must be given one."""
    tree = ast.parse((ROOT / "src" / "06_serve_decisions.py").read_text())
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "log_model"]
    assert calls, "06_serve_decisions no longer logs a model"
    for c in calls:
        kw = {k.arg for k in c.keywords}
        assert kw & {"output_schema", "signature"}, f"log_model at line {c.lineno} has no output schema"
