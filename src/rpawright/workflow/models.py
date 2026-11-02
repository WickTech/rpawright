"""Typed models for rpawright YAML workflows."""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

_KINDS = ("testid", "role", "label", "text", "css", "xpath")


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Target(_Model):
    """One locator candidate: exactly one kind plus optional modifiers."""

    testid: str | None = None
    role: str | None = None
    name: str | None = None
    label: str | None = None
    text: str | None = None
    css: str | None = None
    xpath: str | None = None
    nth: int | None = None
    exact: bool = False

    @model_validator(mode="after")
    def _one_kind(self) -> Self:
        set_kinds = [k for k in _KINDS if getattr(self, k) is not None]
        if len(set_kinds) != 1:
            raise ValueError(f"target needs exactly one of {', '.join(_KINDS)}; got {set_kinds}")
        if self.name is not None and self.role is None:
            raise ValueError("'name' is only allowed together with 'role'")
        return self

    @property
    def kind(self) -> str:
        return next(k for k in _KINDS if getattr(self, k) is not None)


class Retry(_Model):
    times: int = Field(default=0, ge=0)
    delay_ms: int = Field(default=500, ge=0)


class Policy(_Model):
    # allow_domains and heal are parsed and validated in M1 but not enforced.
    allow_domains: list[str] = Field(default_factory=list)
    headless: bool = True
    timeout_ms: int = Field(default=15000, gt=0)
    heal: Literal["propose", "apply_runtime", "off"] = "propose"


class StepCommon(_Model):
    id: str | None = None
    retry: Retry | None = None
    on_error: Literal["fail", "continue"] = "fail"
    timeout_ms: int | None = Field(default=None, gt=0)


class TargetBody(_Model):
    target: list[Target] = Field(min_length=1)
    frame: list[Target] | None = None


class FillBody(TargetBody):
    value: str


class PressBody(_Model):
    key: str
    target: list[Target] | None = None
    frame: list[Target] | None = None


class WaitBody(_Model):
    ms: int | None = Field(default=None, ge=0)
    target: list[Target] | None = None
    frame: list[Target] | None = None
    state: Literal["visible", "hidden"] = "visible"
    url_contains: str | None = None

    @model_validator(mode="after")
    def _one_mode(self) -> Self:
        modes = [m for m in ("ms", "target", "url_contains") if getattr(self, m) is not None]
        if len(modes) != 1:
            raise ValueError(f"wait needs exactly one of ms, target, url_contains; got {modes}")
        return self


class AssertBody(_Model):
    target: list[Target] | None = None
    frame: list[Target] | None = None
    text_contains: str | None = None
    visible: bool | None = None
    url_contains: str | None = None

    @model_validator(mode="after")
    def _needs_subject(self) -> Self:
        if self.target is None and self.url_contains is None:
            raise ValueError("assert needs a target or url_contains")
        return self


class GotoStep(StepCommon):
    goto: str


class ClickStep(StepCommon):
    click: TargetBody


class FillStep(StepCommon):
    fill: FillBody


class PressStep(StepCommon):
    press: str | PressBody


class WaitStep(StepCommon):
    wait: Annotated[int, Field(ge=0)] | WaitBody


class AssertStep(StepCommon):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    assert_: AssertBody = Field(alias="assert")


Step = GotoStep | ClickStep | FillStep | PressStep | WaitStep | AssertStep

_ACTION_NAMES: dict[type[StepCommon], str] = {
    GotoStep: "goto",
    ClickStep: "click",
    FillStep: "fill",
    PressStep: "press",
    WaitStep: "wait",
    AssertStep: "assert",
}


def action_name(step: Step) -> str:
    """Return the YAML key that identifies the step's action."""
    return _ACTION_NAMES[type(step)]


class Workflow(_Model):
    version: Literal[1]
    name: str
    description: str = ""
    policy: Policy = Field(default_factory=Policy)
    steps: list[Step] = Field(min_length=1)

    @model_validator(mode="after")
    def _fill_and_check_ids(self) -> Self:
        seen: set[str] = set()
        for index, step in enumerate(self.steps):
            if step.id is None:
                step.id = f"{action_name(step)}-{index + 1}"
            if step.id in seen:
                raise ValueError(f"duplicate step id '{step.id}'")
            seen.add(step.id)
        return self
