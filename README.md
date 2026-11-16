# Hardware Discovery Test — $0 proof of concept

A separate, read-only test of internet-connected Python on **GitHub Actions**. This repository is public and intentionally contains no private Master files or project research data.

## Run once, manually

1. Open [Free OEM discovery smoke test](https://github.com/criticalcareresearchny-debug/hardware-discovery-test/actions/workflows/public-oem-smoke-test.yml).
2. Select **Run workflow** (on Android the menu may be tucked under the three-dot menu or require a desktop-view browser).
3. Keep the `main` branch selected and select the green **Run workflow** button.
4. Open the newest workflow run and inspect the **Summary**, or open the **Read public manufacturer pages** job for full logs.

The test checks four **existing, known** manufacturer product pages (Sensirion, ST, Analog Devices, ROHM) using only Python standard-library networking. It respects `robots.txt`, attempts to find each model in the visible HTML, and writes the outcome **only to the GitHub Actions run summary and job logs**.

This is a *connectivity/primary-source retrieval test*, not a claim of novel component discovery or independent datasheet verification.

## Safety and cost guardrails

- **Public repo, standard `ubuntu-latest` GitHub-hosted runner:** standard Actions compute is free for public repositories under GitHub's policies.
- **Manual trigger only.** No schedule, automatic recurring jobs, or push trigger.
- **5-minute maximum job execution.** Concurrent runs cancel the older run.
- **No paid APIs, AI APIs, virtual devices, Docker builds, large runners or secrets.**
- **No workflow artifacts, file commits, or downloads retained by the script.**
- **No access to or modification of the authoritative component Master.**
- Only four manufacturer sites, one product page each, plus their robots files. Errors and restrictive robots policies are reported, not bypassed.

Some manufacturer sites may deny requests from GitHub's shared IP addresses. A skipped or failed source is not evidence that the product does not exist.

## Files

- [Manual GitHub workflow](.github/workflows/public-oem-smoke-test.yml)
- [Python source](scripts/oem_smoke_test.py)
