"""JSON Schema export for workflow YAML files."""

from typing import Any

from rpawright.workflow.models import Workflow

SCHEMA_ID = "https://github.com/WickTech/rpawright/schema/workflow.schema.json"


def workflow_json_schema() -> dict[str, Any]:
    """Return the workflow JSON Schema using YAML key names, with a stable `$id`."""
    schema: dict[str, Any] = Workflow.model_json_schema(by_alias=True)
    schema["$id"] = SCHEMA_ID
    return schema
