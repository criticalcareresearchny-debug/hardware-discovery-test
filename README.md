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


## Separate one-off S05 comparison experiment (do not replace the smoke test)

**Start here:** [One-off S05 public OEM comparison ($0)](https://github.com/criticalcareresearchny-debug/hardware-discovery-test/actions/workflows/independent-oem-comparison.yml).

This additional workflow is **manual-only** (\`workflow_dispatch\`) and has a **5-minute maximum job runtime** on a standard public-repository Ubuntu runner. It uses the Python standard library, public OEM pages, and conservative \`robots.txt\` checks. No paid API, organization/private source, private research spreadsheet, Master identity file, model-specific unpublished discovery list, Actions artifact upload, or write permission is used.

**Run once:** GitHub Actions → *One-off S05 public OEM comparison ($0)* → **Run workflow** → choose \`main\` → **Run workflow**. On a narrow Android screen, try desktop site if the button is hidden. Open the resulting run's **Summary**; it reports attempted catalogues, OEM-page access, candidate public product links, page-level model mentions, duration, and geographic reach. Job logs contain machine-readable public source leads. No research-output file needs to be downloaded to a phone.

**Interpretation:** The workflow does not assign Research IDs, certify new independent devices, establish C01–C32 classifications, or perform read-only Master identity matching. The current research team must independently check original product/datasheet evidence, variants/assembly boundaries, power and interfaces, regional origin, and Master overlap *outside this public test repository*. OEM pages can be blocked; a missing page is not a nonexistent part. Automated leads are not a replacement for the existing research method, and a comparison report should distinguish demonstrable gains from untested potential.

The original four-OEM smoke test is retained as a connectivity control and runs before the new catalogue scan; its result is not a research-quality baseline. Nothing changes the ongoing S05 work or the authoritative Master.
