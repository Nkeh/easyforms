"""Screenshot pass for manual visual review of the app shell / restyled pages.

Not part of the Django image or its dependency groups — run from the official
Playwright Python image, attached to the compose network:

    docker run --rm --network easyforms_default \\
      -v "$(pwd):/work" -w /work \\
      mcr.microsoft.com/playwright/python:v1.47.0-jammy \\
      python scripts/screenshots.py

Requires demo data seeded first (var/seed_demo.py) — reads its ids/creds from
var/demo_seed.json.
"""

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright

WIDTHS = [1280, 390]
VIEWPORT_HEIGHT = 900


def load_seed(seed_file: Path) -> dict:
    if not seed_file.exists():
        raise SystemExit(f"{seed_file} not found — run var/seed_demo.py first.")
    return json.loads(seed_file.read_text())


def login(page, base_url: str, email: str, password: str) -> None:
    page.goto(f"{base_url}/login")
    page.fill("#id_username", email)
    page.fill("#id_password", password)
    page.click("button[type=submit]")
    page.wait_for_url(f"{base_url}/dashboard")


def shoot(page, out_dir: Path, name: str, width: int) -> None:
    page.set_viewport_size({"width": width, "height": VIEWPORT_HEIGHT})
    page.wait_for_load_state("networkidle")
    page.screenshot(path=str(out_dir / f"{name}-{width}.png"), full_page=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://web:8000")
    parser.add_argument("--seed-file", default="var/demo_seed.json")
    parser.add_argument("--out-dir", default="var/screenshots")
    args = parser.parse_args()

    seed = load_seed(Path(args.seed_file))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    form_id = seed["form_with_data_id"]
    empty_form_id = seed["form_empty_id"]
    submission_id = seed["sample_submission_id"]

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()
        page = context.new_page()

        # Unauthenticated pages first.
        page.goto(f"{args.base_url}/login")
        for width in WIDTHS:
            shoot(page, out_dir, "login", width)
        page.goto(f"{args.base_url}/signup")
        for width in WIDTHS:
            shoot(page, out_dir, "signup", width)
        page.goto(f"{args.base_url}/thanks")
        for width in WIDTHS:
            shoot(page, out_dir, "thanks", width)

        login(page, args.base_url, seed["email"], seed["password"])

        pages = [
            ("dashboard", f"{args.base_url}/dashboard"),
            ("form-detail", f"{args.base_url}/forms/{form_id}"),
            ("submissions-all", f"{args.base_url}/forms/{form_id}/submissions?status=all"),
            ("submissions-ham", f"{args.base_url}/forms/{form_id}/submissions?status=ham"),
            ("submissions-spam", f"{args.base_url}/forms/{form_id}/submissions?status=spam"),
            (
                "submissions-empty",
                f"{args.base_url}/forms/{empty_form_id}/submissions?status=all",
            ),
            (
                "submission-detail",
                f"{args.base_url}/forms/{form_id}/submissions/{submission_id}",
            ),
            ("settings", f"{args.base_url}/settings"),
        ]
        for name, url in pages:
            page.goto(url)
            for width in WIDTHS:
                shoot(page, out_dir, name, width)

        # Mobile drawer open, on the dashboard, at the mobile width.
        page.goto(f"{args.base_url}/dashboard")
        page.set_viewport_size({"width": 390, "height": VIEWPORT_HEIGHT})
        page.wait_for_load_state("networkidle")
        page.click("#mobile-menu-toggle")
        page.wait_for_timeout(300)  # let the open transition settle
        page.screenshot(path=str(out_dir / "dashboard-drawer-390.png"), full_page=True)

        browser.close()

    print(f"Screenshots written to {out_dir}")


if __name__ == "__main__":
    main()
