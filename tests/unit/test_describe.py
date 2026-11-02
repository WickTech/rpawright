import pytest

from rpawright.runner.locate import describe
from rpawright.workflow.models import Target

T = Target.model_validate


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({"css": "#email"}, "css=#email"),
        ({"testid": "save-main"}, "testid=save-main"),
        ({"label": "Email"}, "label=Email"),
        ({"text": "Save"}, "text=Save"),
        ({"xpath": "//a"}, "xpath=//a"),
        ({"role": "button", "name": "Sign in"}, 'role=button[name="Sign in"]'),
        ({"role": "button"}, "role=button"),
        ({"css": "li", "nth": 2}, "css=li[nth=2]"),
        ({"role": "button", "name": "Go", "nth": 0}, 'role=button[name="Go"][nth=0]'),
    ],
)
def test_describe(raw: dict[str, object], expected: str) -> None:
    assert describe(T(raw)) == expected
