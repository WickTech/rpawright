"""Typed models for rpawright YAML workflows."""

from collections.abc import Iterator
from typing import Annotated, Any, ClassVar, Literal, Self

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    Tag,
    field_validator,
    model_validator,
)

from rpawright.workflow.expressions import is_whole_expression

RESERVED_NAMES = frozenset({"inputs", "vars", "secret", "asset", "env", "today"})
_JINJA_WORDS = frozenset(
    {"true", "false", "none", "True", "False", "None", "and", "or", "not", "in", "is", "if", "else"}
)


def _check_var_name(name: str) -> str:
    if not name.isidentifier():
        raise ValueError(f"'{name}' is not a valid variable name (use letters, digits, '_')")
    if name in RESERVED_NAMES:
        raise ValueError(f"'{name}' is a reserved name")
    if name in _JINJA_WORDS:
        raise ValueError(f"'{name}' cannot be used as a variable name")
    return name


VarName = Annotated[str, AfterValidator(_check_var_name)]

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
    # NATIVE_FIELDS keep a whole-string {{ expr }} result as a native object (R6);
    # LAZY_FIELDS hold nested steps and are never rendered up front.
    NATIVE_FIELDS: ClassVar[frozenset[str]] = frozenset()
    LAZY_FIELDS: ClassVar[frozenset[str]] = frozenset({"on_error"})

    id: str | None = None
    retry: Retry | None = None
    on_error: Literal["fail", "continue"] | list["Step"] = "fail"
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


class SelectBody(TargetBody):
    value: str | None = None
    label: str | None = None

    @model_validator(mode="after")
    def _one_choice(self) -> Self:
        chosen = [k for k in ("value", "label") if getattr(self, k) is not None]
        if len(chosen) != 1:
            raise ValueError(f"select needs exactly one of value, label; got {chosen}")
        return self


class ExtractBody(TargetBody):
    into: VarName


class DownloadBody(_Model):
    to: str


class UploadBody(TargetBody):
    file: str


class ScreenshotBody(_Model):
    path: str | None = None
    full_page: bool = False


class HttpBody(_Model):
    NATIVE_FIELDS: ClassVar[frozenset[str]] = frozenset({"json_", "params"})

    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"] = "GET"
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)
    json_: Any = Field(default=None, alias="json")
    body: str | None = None
    into: VarName | None = None
    expect_status: int | list[int] | None = None

    @model_validator(mode="after")
    def _json_xor_body(self) -> Self:
        if self.json_ is not None and self.body is not None:
            raise ValueError("http takes either json or body, not both")
        return self


class ReadCsvBody(_Model):
    path: str
    into: VarName


class WriteCsvBody(_Model):
    NATIVE_FIELDS: ClassVar[frozenset[str]] = frozenset({"rows"})

    path: str
    rows: str | list[dict[str, Any]]


class ReadXlsxBody(_Model):
    path: str
    sheet: str | None = None
    into: VarName


class WriteXlsxBody(_Model):
    NATIVE_FIELDS: ClassVar[frozenset[str]] = frozenset({"rows"})

    path: str
    rows: str | list[dict[str, Any]]
    sheet: str | None = None


class ForEachBody(_Model):
    NATIVE_FIELDS: ClassVar[frozenset[str]] = frozenset({"in_"})
    LAZY_FIELDS: ClassVar[frozenset[str]] = frozenset({"steps"})

    in_: str | list[Any] = Field(alias="in")
    as_: VarName = Field(alias="as")
    steps: list["Step"] = Field(min_length=1)


class CallBody(_Model):
    NATIVE_FIELDS: ClassVar[frozenset[str]] = frozenset({"inputs"})

    bot: str
    inputs: dict[str, Any] = Field(default_factory=dict)


class LogBody(_Model):
    message: str


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


class SelectStep(StepCommon):
    select: SelectBody


class HoverStep(StepCommon):
    hover: TargetBody


class ExtractTextStep(StepCommon):
    extract_text: ExtractBody


class ExtractTableStep(StepCommon):
    extract_table: ExtractBody


class DownloadStep(StepCommon):
    download: DownloadBody


class UploadStep(StepCommon):
    upload: UploadBody


class ScreenshotStep(StepCommon):
    screenshot: ScreenshotBody


class HttpStep(StepCommon):
    http: HttpBody


class ReadCsvStep(StepCommon):
    read_csv: ReadCsvBody


class WriteCsvStep(StepCommon):
    write_csv: WriteCsvBody


class ReadXlsxStep(StepCommon):
    read_xlsx: ReadXlsxBody


class WriteXlsxStep(StepCommon):
    write_xlsx: WriteXlsxBody


class SetStep(StepCommon):
    NATIVE_FIELDS: ClassVar[frozenset[str]] = frozenset({"set"})

    set: dict[VarName, Any] = Field(min_length=1)


class IfStep(StepCommon):
    NATIVE_FIELDS: ClassVar[frozenset[str]] = frozenset({"if_"})
    LAZY_FIELDS: ClassVar[frozenset[str]] = frozenset({"on_error", "then", "else_"})

    if_: str | bool = Field(alias="if")
    then: list["Step"] = Field(min_length=1)
    else_: list["Step"] = Field(default_factory=list, alias="else")

    @field_validator("if_")
    @classmethod
    def _bool_or_whole_expression(cls, value: str | bool) -> str | bool:
        if isinstance(value, str) and not is_whole_expression(value):
            raise ValueError(
                'if must be true/false or a single {{ expression }} (e.g. "{{ n > 1 }}")'
            )
        return value


class ForEachStep(StepCommon):
    for_each: ForEachBody


class CallStep(StepCommon):
    call: CallBody


class PauseStep(StepCommon):
    pause: str | None


class LogStep(StepCommon):
    log: LogBody


ACTION_NAMES: dict[type[StepCommon], str] = {
    GotoStep: "goto",
    ClickStep: "click",
    FillStep: "fill",
    PressStep: "press",
    WaitStep: "wait",
    AssertStep: "assert",
    SelectStep: "select",
    HoverStep: "hover",
    ExtractTextStep: "extract_text",
    ExtractTableStep: "extract_table",
    DownloadStep: "download",
    UploadStep: "upload",
    ScreenshotStep: "screenshot",
    HttpStep: "http",
    ReadCsvStep: "read_csv",
    WriteCsvStep: "write_csv",
    ReadXlsxStep: "read_xlsx",
    WriteXlsxStep: "write_xlsx",
    SetStep: "set",
    IfStep: "if",
    ForEachStep: "for_each",
    CallStep: "call",
    PauseStep: "pause",
    LogStep: "log",
}
_ACTION_KEYS = frozenset(ACTION_NAMES.values())


def _step_tag(value: Any) -> str | None:
    """Pick the union member by the single action key; None for zero or several."""
    if isinstance(value, dict):
        found = [k for k in value if k in _ACTION_KEYS]
        return found[0] if len(found) == 1 else None
    if isinstance(value, StepCommon):
        return ACTION_NAMES.get(type(value))
    return None


Step = Annotated[
    Annotated[GotoStep, Tag("goto")]
    | Annotated[ClickStep, Tag("click")]
    | Annotated[FillStep, Tag("fill")]
    | Annotated[PressStep, Tag("press")]
    | Annotated[WaitStep, Tag("wait")]
    | Annotated[AssertStep, Tag("assert")]
    | Annotated[SelectStep, Tag("select")]
    | Annotated[HoverStep, Tag("hover")]
    | Annotated[ExtractTextStep, Tag("extract_text")]
    | Annotated[ExtractTableStep, Tag("extract_table")]
    | Annotated[DownloadStep, Tag("download")]
    | Annotated[UploadStep, Tag("upload")]
    | Annotated[ScreenshotStep, Tag("screenshot")]
    | Annotated[HttpStep, Tag("http")]
    | Annotated[ReadCsvStep, Tag("read_csv")]
    | Annotated[WriteCsvStep, Tag("write_csv")]
    | Annotated[ReadXlsxStep, Tag("read_xlsx")]
    | Annotated[WriteXlsxStep, Tag("write_xlsx")]
    | Annotated[SetStep, Tag("set")]
    | Annotated[IfStep, Tag("if")]
    | Annotated[ForEachStep, Tag("for_each")]
    | Annotated[CallStep, Tag("call")]
    | Annotated[PauseStep, Tag("pause")]
    | Annotated[LogStep, Tag("log")],
    Discriminator(_step_tag),
]

_RECURSIVE: list[type[BaseModel]] = [StepCommon, *ACTION_NAMES, ForEachBody]
for _model in _RECURSIVE:
    _model.model_rebuild()


def action_name(step: StepCommon) -> str:
    """Return the YAML key that identifies the step's action."""
    return ACTION_NAMES[type(step)]


def child_blocks(step: StepCommon) -> list[tuple[str, list[Step]]]:
    """Nested step lists of ``step`` as (label, steps): then, else, steps, on_error."""
    blocks: list[tuple[str, list[Step]]] = []
    if isinstance(step, IfStep):
        blocks += [("then", step.then), ("else", step.else_)]
    if isinstance(step, ForEachStep):
        blocks.append(("steps", step.for_each.steps))
    if isinstance(step.on_error, list):
        blocks.append(("on_error", step.on_error))
    return [(label, steps) for label, steps in blocks if steps]


def iter_steps(steps: list[Step]) -> Iterator[Step]:
    """Yield every step in pre-order, descending into nested blocks."""
    for step in steps:
        yield step
        for _, block in child_blocks(step):
            yield from iter_steps(block)


class InputSpec(_Model):
    type: Literal["string", "int", "float", "bool"] = "string"
    default: str | int | float | bool | None = None

    @model_validator(mode="after")
    def _default_matches_type(self) -> Self:
        d = self.default
        if d is None or (isinstance(d, str) and "{{" in d):
            return self
        ok = {
            "string": isinstance(d, str),
            "int": isinstance(d, int) and not isinstance(d, bool),
            "float": isinstance(d, int | float) and not isinstance(d, bool),
            "bool": isinstance(d, bool),
        }[self.type]
        if not ok:
            raise ValueError(f"default {d!r} does not match type {self.type}")
        return self


class Workflow(_Model):
    version: Literal[1]
    name: str
    description: str = ""
    policy: Policy = Field(default_factory=Policy)
    inputs: dict[VarName, InputSpec] = Field(default_factory=dict)
    vars: dict[VarName, Any] = Field(default_factory=dict)
    steps: list[Step] = Field(min_length=1)

    @model_validator(mode="after")
    def _fill_and_check_ids(self) -> Self:
        seen: set[str] = set()
        for number, step in enumerate(iter_steps(self.steps), start=1):
            if step.id is None:
                step.id = f"{action_name(step)}-{number}"
            if step.id in seen:
                raise ValueError(f"duplicate step id '{step.id}'")
            seen.add(step.id)
        return self
