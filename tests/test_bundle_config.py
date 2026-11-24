"""The bundle, the job's notebook parameters, and the app config must agree with each other."""

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = yaml.safe_load((ROOT / "databricks.yml").read_text())
APP_YAML = yaml.safe_load((ROOT / "app" / "app.yaml").read_text())
APP_ENV = {e["name"]: e.get("value") for e in APP_YAML["env"]}


def _var(name):
    return BUNDLE["variables"][name]["default"]


def test_every_job_notebook_exists_and_declares_its_parameters():
    for task in BUNDLE["resources"]["jobs"]["nbo_demo_build"]["tasks"]:
        nb = ROOT / task["notebook_task"]["notebook_path"]
        assert nb.exists(), f"{task['task_key']}: {nb} not found"
        widgets = set(re.findall(r'dbutils\.widgets\.text\("(\w+)"', nb.read_text()))
        params = set(task["notebook_task"].get("base_parameters", {}))
        assert params <= widgets, f"{nb.name} gets parameters it does not declare: {params - widgets}"


def test_task_dependencies_point_at_real_tasks():
    tasks = BUNDLE["resources"]["jobs"]["nbo_demo_build"]["tasks"]
    keys = {t["task_key"] for t in tasks}
    for t in tasks:
        for d in t.get("depends_on", []):
            assert d["task_key"] in keys


def test_app_points_at_the_endpoint_and_schema_the_job_builds():
    assert APP_ENV["NBO_ENDPOINT"] == _var("endpoint_name")
    assert APP_ENV["NBO_SCHEMA"] == f"{_var('catalog')}.{_var('schema')}"


def test_app_source_and_command_exist():
    app = BUNDLE["resources"]["apps"]["nbo_app"]
    src = ROOT / app["source_code_path"]
    assert (src / APP_YAML["command"][-1]).exists()


def test_default_target_is_the_live_workspace():
    defaults = [n for n, t in BUNDLE["targets"].items() if t.get("default")]
    assert defaults == ["trial"]
    assert BUNDLE["targets"]["trial"]["workspace"]["host"] == "https://dbc-8d181d91-4a82.cloud.databricks.com"


def test_app_requirements_cover_its_imports():
    reqs = (ROOT / "app" / "requirements.txt").read_text().lower()
    for pkg in ["fastapi", "databricks-sql-connector", "databricks-sdk", "pandas"]:
        assert pkg in reqs


def test_job_notebooks_do_not_import_streamlit_modules():
    """Job compute has no Streamlit; a notebook must not import an app module that needs it."""
    import ast
    needs_st = {p.stem for p in (ROOT / "app").glob("*.py") if re.search(r"^import streamlit", p.read_text(), re.M)}
    for nb in (ROOT / "src").glob("*.py"):
        for node in ast.walk(ast.parse(nb.read_text())):
            mods = ([a.name for a in node.names] if isinstance(node, ast.Import)
                    else [node.module] if isinstance(node, ast.ImportFrom) else [])
            bad = {m.split(".")[0] for m in mods if m} & needs_st
            assert not bad, f"{nb.name}:{node.lineno} imports {bad}, which needs Streamlit"
