"""Keyboard focus / reduced-motion / HTMX / copy-button interaction checks.

Same runtime as scripts/screenshots.py, but joins the `web` container's own
network namespace (rather than just attaching to the compose network) so the
page loads as plain "http://localhost:8000" — the copy-button check uses
navigator.clipboard, which browsers only expose on a secure context, and
"localhost" (unlike the compose DNS name "web") is always treated as one:

    docker run --rm --network container:easyforms-web-1 \\
      -v "$(pwd):/work" -w /work \\
      mcr.microsoft.com/playwright/python:v1.47.0-jammy \\
      python scripts/interaction_checks.py

Requires demo data seeded first (var/seed_demo.py) — reads its ids/creds from
var/demo_seed.json. Exits non-zero and prints failures if any check fails.
"""

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

failures = []


def check(label: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}" + (f" — {detail}" if detail else ""))
    if not condition:
        failures.append(label)


def login(page, base_url: str, email: str, password: str) -> None:
    page.goto(f"{base_url}/login")
    page.fill("#id_username", email)
    page.fill("#id_password", password)
    page.click("button[type=submit]")
    page.wait_for_url(f"{base_url}/dashboard")


def check_focus_visible(page, url: str, label: str) -> None:
    page.goto(url)
    page.keyboard.press("Tab")
    seen = []
    for _ in range(8):
        info = page.evaluate(
            """() => {
                const el = document.activeElement;
                if (!el || el === document.body) return null;
                const cs = getComputedStyle(el);
                const visible = cs.outlineStyle !== 'none' && cs.outlineWidth !== '0px';
                return {tag: el.tagName, text: (el.textContent || '').trim().slice(0, 40), visible};
            }"""
        )
        if info is None:
            break
        seen.append(info)
        page.keyboard.press("Tab")

    check(
        f"{label}: focus outline visible on every tab stop",
        all(item["visible"] for item in seen) and len(seen) > 0,
        f"{len(seen)} stops: " + ", ".join(f"{i['tag']}:{i['text']!r}" for i in seen[:5]),
    )


def check_reduced_motion(base_url: str, email: str, password: str) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(reduced_motion="reduce")
        page = context.new_page()
        login(page, base_url, email, password)
        duration = page.evaluate(
            """() => {
                const el = document.querySelector('.btn');
                return el ? getComputedStyle(el).transitionDuration : null;
            }"""
        )
        seconds = float(duration.replace("s", "")) if duration else None
        check(
            "prefers-reduced-motion: transitions collapse to ~instant",
            seconds is not None and seconds <= 0.001,
            f"transitionDuration={duration!r}",
        )
        browser.close()


def check_htmx_filter_swap(page, base_url: str, form_id: str) -> None:
    page.goto(f"{base_url}/forms/{form_id}/submissions?status=all")
    page.click('[data-filter-value="spam"]')
    page.wait_for_load_state("networkidle")
    is_active = page.eval_on_selector(
        '[data-filter-value="spam"]', "el => el.classList.contains('tab-active')"
    )
    check(
        "HTMX filter swap: spam tab becomes active and URL updates",
        is_active and "status=spam" in page.url,
        f"url={page.url}",
    )


def check_label_flip_and_undo(page, base_url: str, form_id: str, submission_id: str) -> None:
    page.goto(f"{base_url}/forms/{form_id}/submissions/{submission_id}")
    page.click('#submission-status button[type="submit"]')
    page.wait_for_selector(".toast")
    flipped_pill = page.eval_on_selector(
        "#submission-status .pill:not(.pill-warn)", "el => el.textContent.trim()"
    )
    check(
        "Label flip: status pill updates and a toast with Undo appears",
        flipped_pill == "Spam" and page.is_visible(".toast >> text=Undo"),
        f"pill={flipped_pill!r}",
    )

    page.click(".toast >> text=Undo")
    page.wait_for_timeout(300)
    restored_pill = page.eval_on_selector(
        "#submission-status .pill:not(.pill-warn)", "el => el.textContent.trim()"
    )
    check(
        "Label flip: Undo restores the original status",
        restored_pill == "Ham",
        f"pill={restored_pill!r}",
    )


def check_copy_button(page, base_url: str, form_id: str) -> None:
    page.goto(f"{base_url}/forms/{form_id}")
    page.click('button[data-copy-target="endpoint-url"]')
    page.wait_for_timeout(200)
    label_text = page.eval_on_selector(
        'button[data-copy-target="endpoint-url"] [data-copy-label]', "el => el.textContent"
    )
    check(
        "Copy button: label flips to 'Copied' feedback",
        "Copied" in label_text,
        f"label={label_text!r}",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--seed-file", default="var/demo_seed.json")
    args = parser.parse_args()

    seed = json.loads(Path(args.seed_file).read_text())
    form_id = seed["form_with_data_id"]
    possible_spam_id = seed["sample_possible_spam_id"]

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()
        context.grant_permissions(["clipboard-read", "clipboard-write"])
        page = context.new_page()
        login(page, args.base_url, seed["email"], seed["password"])

        check_focus_visible(page, f"{args.base_url}/dashboard", "dashboard")
        check_focus_visible(page, f"{args.base_url}/forms/{form_id}", "form detail")
        check_htmx_filter_swap(page, args.base_url, form_id)
        check_copy_button(page, args.base_url, form_id)
        check_label_flip_and_undo(page, args.base_url, form_id, possible_spam_id)

        browser.close()

    check_reduced_motion(args.base_url, seed["email"], seed["password"])

    if failures:
        print(f"\n{len(failures)} check(s) failed: {failures}")
        sys.exit(1)
    print("\nAll interaction checks passed.")


if __name__ == "__main__":
    main()
