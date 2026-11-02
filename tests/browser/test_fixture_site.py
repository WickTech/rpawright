from playwright.sync_api import Page, expect


def test_login_with_both_fields_reaches_dashboard(page: Page, site_url: str) -> None:
    page.goto(f"{site_url}/login.html")
    page.get_by_label("Email").fill("user@example.com")
    page.get_by_label("Password").fill("secret")
    page.get_by_role("button", name="Sign in").click()
    expect(page.get_by_role("heading", name="Welcome")).to_be_visible()
    expect(page.locator("table.invoices tr")).to_have_count(3)


def test_login_with_empty_fields_stays_on_login(page: Page, site_url: str) -> None:
    page.goto(f"{site_url}/login.html")
    page.get_by_role("button", name="Sign in").click()
    expect(page).to_have_url(f"{site_url}/login.html")
