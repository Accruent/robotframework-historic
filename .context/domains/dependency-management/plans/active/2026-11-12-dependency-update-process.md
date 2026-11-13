---
date: 2026-11-12
author: Neil Howell
domain: dependency-management
jira: QE-7618
research: .context/domains/dependency-management/research/current/2026-11-12-dependency-update-process.md
status: draft
phases: 5
---

# QE-7618: Dependency Update Process (Dependabot Cadence, PR Build Check, Open Updates) — Implementation Plan

## Overview
Close the stale Dependabot PRs and update dependencies directly in a single verified change. Move the image to `python:3.14`, which matches the rest of the automation stack and is required by the setuptools alert fixes. Remove the unused `robotframework` requirement. Switch Dependabot to one grouped weekly PR. Add a PR workflow that builds the image without pushing, starts the compose stack and runs smoke probes, then make it a required check on `master`. Document the post-release smoke check and image rollback in the repo and on Confluence. Retire `pipeline.groovy` if Jenkins does not use it. Resume Dependabot last.

---

## Current State Analysis

*(Full details in research artifact. Key facts for implementation:)*

- `.github/dependabot.yml:1-11`: `pip` at `/`, `interval: daily`, `open-pull-requests-limit: 10`, no `groups`. Version updates are auto-paused for inactivity (last merged Dependabot PR is #151).
- Open PRs #158 (setuptools `~=84.0.0`), #159 (robotframework `~=7.5`) and #160 (pytz `~=2026.4`) are all behind PyPI (84.2.1 / 7.5.1 / 2026.6).
- Open alerts: #4 setuptools (Medium, fixed 83.0.0) and #5 setuptools (Low, fixed 84.1.0). #158 does not fix #5. setuptools >=83 requires Python >=3.10.
- `Dockerfile:1` `FROM python:3.9`. `Dockerfile:10` `pip install .`. The full (non-slim) image provides the compiler and MySQL headers that `mysqlclient` (via `flask-mysqldb`) needs.
- `requirements.txt:1-7` feeds `install_requires` (`setup.py:8-9`, `:31`). `robotframework` is not imported anywhere. `robotframework-historic-parser` declares its own `robotframework>=6.0` and does not depend on this package.
- `.github/workflows/build-and-publish.yml:22-26` runs only on push, dispatch or merged PR. No workflow runs on open PRs. `master` has no required status checks.
- `version.py:3` `VERSION = "0.2.2"`. Publishing without a bump overwrites `:0.2.2`.
- Production: `rfhistoric-depl` in `legion-historic` (context `Legion-a6d6a7a`), image `.../qe_docker/library/rfhistoric:latest`, `imagePullPolicy: Always`. Deploy = delete pod or `kubectl rollout restart`. `rollout undo` does not restore an older image because the tag is unchanged.
- `docker/init.sql` seeds `rf_full_data` (execution id 1 exists), `roomba_sync_data`, `empty_project`.
- No tests, no smoke docs, no rollback docs. `README.md` covers install/usage only.

### Pre-execution Verification (2026-11-12, temp copies, worktree untouched)
- `python:3.14` build with the Phase 1 requirements succeeds: `mysqlclient` 2.3.1 compiles on the full image, `bcrypt` 5.0.0 uses its `abi3` wheel, `setuptools` 84.2.1, `pytz` 2026.6. `import robot` → `ModuleNotFoundError`.
- Compose smoke A/B (ports 5099/8099): `python:3.9` baseline ready in 14 s, `python:3.14` ready in 12.8 s. Both return 200 for `/`, dashboard, `metrics/1`, tmetrics and compare, and 403 for unauthenticated `edelete/1`. `OperationalError` lines appear in both while MySQL initialises (expected). The CI poll must tolerate this.
- An earlier one-off 3.14 compose run never reached `db` (errno 99) within 3 minutes. The A/B rerun did not reproduce it. Treated as transient; see Risks.
- Deployment container name confirmed: `rfhistoric-app`.
- `robotframework-historic-parser` has one open low `setuptools` alert.
- Not yet verified (Phase 0): `:0.2.2` in ProGet (anonymous access denied), Jenkins usage of `pipeline.groovy` (no credentials in session).

---

## Desired End State

- `requirements.txt`: `config~=0.5.1`, `Flask~=3.1.3`, `bcrypt~=5.0.0`, `flask-mysqldb~=2.0.0`, `pytz~=2026.6`, `setuptools~=84.2`. `robotframework` removed.
- `Dockerfile:1` `FROM python:3.14`. The image builds and serves the seeded app.
- Dependabot alerts #4 and #5 auto-close after merge. PRs #158/#159/#160 are closed with a comment linking the replacement PR.
- `.github/dependabot.yml`: `pip` and `github-actions` ecosystems, `interval: weekly`, one group per ecosystem, so at most one PR per ecosystem per week.
- `.github/workflows/pr-build.yml` runs on every PR to `master` (including Dependabot PRs), needs no secrets, builds without pushing, starts compose and passes the smoke probes. It is a required status check on `master`.
- `docs/RELEASE.md` documents the release, smoke check and rollback, and `README.md` links to it. Confluence page 1336247055 is updated.
- `version.py` is bumped to `0.3.0` so the previous `:0.2.2` image stays available for rollback.
- `pipeline.groovy` is removed (only if Phase 0 confirms Jenkins does not use it).
- Dependabot version updates are resumed and produce a grouped PR.

---

## What We're NOT Doing

- No pytest suite or test framework. QE-7619 adds tests to `pr-build.yml`.
- No changes to `app.py` routes, templates or schema.
- No change to the deploy mechanism (`:latest` + pod restart) or K8s manifests in `ops_azure_ansible_k8`.
- No compose healthchecks. The workflow polls with retries instead.
- No changes to `robotframework-historic-parser`. Its `setuptools~=84.0.0` pin likely has the same alert #5; flag it to the parser owner separately.
- No `-slim` base image (would need explicit `build-essential`/`default-libmysqlclient-dev`/`pkg-config`).

---

## Implementation Approach

A single feature PR carries Phases 1–3. Phase 0 is a read-only pre-check. Phase 4 contains the post-merge and admin steps: close PRs, branch protection, release, Confluence, resume Dependabot. The new PR workflow validates its own PR, so the dependency bump is the first change verified by it. Run all commands with the system Python or inside Docker. Do not use virtual environments. Use `gh auth switch -u neiljhowell` before `gh` commands.

---

## Phase 0: Pre-checks (read-only)

### Steps
1. Jenkins: search job configs for this repo or `pipeline.groovy` (use the `jenkins-api-job-operations` skill). Record the result here.
   - No job found → delete `pipeline.groovy` in Phase 2.
   - Job found → keep the file, record the job URL, and drop that step.
2. Record the production digest for rollback reference: `kubectl --context Legion-a6d6a7a -n legion-historic get pod -l app=rfhistoric-app -o jsonpath="{.items[*].status.containerStatuses[*].imageID}"` → expect `sha256:977709c9…` (or newer).
3. Confirm `:0.2.2` exists in ProGet (use the `proget-api-evidence` skill).

### Results (2026-11-12)
- Jenkins (irongiant): all 2016 job `config.xml` files scanned, 0 fetch failures, 0 jobs with SCM `robotframework-historic` (parser excluded). Other jobs mention `rfhistoric` only as a results target. → Delete `pipeline.groovy` in Phase 2.
- Production pod `rfhistoric-depl-7cfc654744-7phmk` (started 2026-11-12T13:57Z) runs `rfhistoric@sha256:977709c9e1f8dea971f1e0242b06aecbc6dc7c24be7ac78456bae52cf671daec` (OCI index, still pullable from ProGet).
- ProGet: `:0.2.2` and `:latest` both resolve to index `sha256:2c0790b7e470bfcdb9b1b6d1c85e380bf8c3f58ccea4f10f370f3df7ceb42211`. This differs from the running digest, so `:latest` was republished after the pod pulled it. Rollback docs should use the recorded `@sha256:977709c9…` digest, not `:0.2.2`.

### Success Criteria
- [x] Jenkins usage of `pipeline.groovy` decided and recorded
- [x] Current digest and `:0.2.2` tag recorded

---

## Phase 1: Dependencies and Base Image

### Changes Required

#### 1. `requirements.txt`
- Delete line 1 `robotframework~=7.4`.
- `pytz~=2026.2` → `pytz~=2026.6`.
- `setuptools~=82.0.1` → `setuptools~=84.2` (`>=84.2,<85`, which covers both alert fix versions).

#### 2. `Dockerfile:1`
`FROM python:3.9` → `FROM python:3.14`. No other Dockerfile changes.

#### 3. `version.py:3`
`VERSION = "0.2.2"` → `VERSION = "0.3.0"` (base image and dependency change, and a new tag preserves `:0.2.2` for rollback).

#### 4. `setup.py`
Leave the `Framework :: Robot Framework` classifier as is (metadata only, still describes the domain). No other changes.

### Success Criteria

#### Automated Verification
- [x] `docker compose build rfhistoric` → succeeds; `mysqlclient` and `bcrypt` install without errors
- [x] `docker compose run --rm --no-deps --entrypoint python rfhistoric -c "import sys, flask, MySQLdb, bcrypt, pytz, setuptools; print(sys.version, setuptools.__version__)"` → `3.14.x`, `84.2.x`
- [x] `docker compose run --rm --no-deps --entrypoint python rfhistoric -c "import robot"` → `ModuleNotFoundError`
- [x] `docker compose down -v ; docker compose up -d` → all 3 services running
- [x] `(Invoke-WebRequest http://localhost:5001/).StatusCode` → `200`
- [x] `try { Invoke-WebRequest http://localhost:5001/rf_full_data/edelete/1 } catch { $_.Exception.Response.StatusCode.value__ }` → `403`
- [x] `/rf_full_data/dashboard`, `/rf_full_data/metrics/1`, `/rf_full_data/tmetrics`, `/rf_full_data/compare` → `200`

Results (2026-11-12): Python 3.14.10, setuptools 84.2.1. Ruling: port 5001/8081 is held by the running QE-7617 stack, so the compose smoke ran on a temp copy (project `rfh7618`, ports 5098/8098) — stops nothing in QE-7617 — if wrong, rerun on 5001 after QE-7617 is stopped. Logs: 6 `Traceback`, all `OperationalError` during MySQL init (expected); 0 `DeprecationWarning`.

#### Manual Verification
- [x] Log in as Lead and as Viewer (per `.github/copilot-instructions.md`); nav-bar button visibility unchanged
- [x] `docker compose logs rfhistoric` → no `Traceback` or `DeprecationWarning` from app code

---

## Phase 2: PR Build Check, Dependabot Config, Repo Cleanup

### Changes Required

#### 1. `.github/workflows/pr-build.yml` (new)
- `name: PR Build Check`. Trigger: `pull_request` `types: [opened, synchronize, reopened]`, `branches: [master]`. `permissions: contents: read`. No `secrets` references.
- Job `build-and-smoke` (this is the required-check name), `runs-on: ubuntu-latest`:
  1. `actions/checkout@v4`
  2. `docker compose build rfhistoric` (no `docker login`, no push)
  3. `docker compose up -d`
  4. Smoke step (bash): poll `curl -fsS --retry 30 --retry-delay 2 --retry-all-errors -o /dev/null http://localhost:5001/` (waits for MySQL init). Then assert `200` for `/rf_full_data/dashboard`, `/rf_full_data/metrics/1`, `/rf_full_data/tmetrics`, `/rf_full_data/compare`, and `403` for `/rf_full_data/edelete/1`, using `curl -s -o /dev/null -w '%{http_code}'`. Fail with `[FAIL] <route> got <code>` on mismatch.
  5. `if: failure()` → `docker compose logs`
  6. `if: always()` → `docker compose down -v`
- QE-7619 will add its pytest step after step 4; no stub is added here.

#### 2. `.github/dependabot.yml`
```yaml
version: 2
updates:
  - package-ecosystem: pip
    directory: "/"
    schedule:
      interval: weekly
      day: monday
      time: "09:00"
      timezone: US/Central
    open-pull-requests-limit: 5
    reviewers: [neiljhowell]
    groups:
      pip-all:
        patterns: ["*"]
  - package-ecosystem: github-actions
    directory: "/"
    schedule:
      interval: weekly
      day: monday
      time: "09:00"
      timezone: US/Central
    reviewers: [neiljhowell]
    groups:
      actions-all:
        patterns: ["*"]
```
Security updates are not affected by `schedule` and still open on demand.
Ruling (2026-11-12): `reviewers` removed — GitHub dropped it from the `dependabot.yml` schema in favour of CODEOWNERS; no CODEOWNERS file was added (it would auto-request review on every PR) — if wrong, Dependabot PRs get no auto-assigned reviewer.

#### 3. `pipeline.groovy`
Delete it (only if Phase 0 found no Jenkins job).

### Success Criteria

#### Automated Verification
- [x] `docker run --rm -v "${PWD}:/repo" -w /repo rhysd/actionlint:latest` → no errors
- [x] `python -c "import yaml; yaml.safe_load(open('.github/dependabot.yml'))"` → exit 0 (if PyYAML is available on the system Python; otherwise rely on GitHub's validation in Phase 4)
- [x] Push the branch and open the PR → `PR Build Check / build-and-smoke` appears and passes (PR #163)
- [x] Negative check: push a temporary commit that changes the expected `edelete` code to `200` → check fails with `[FAIL]`; revert the commit → check passes (run 43287647250 failed with `[FAIL] /rf_full_data/edelete/1 got 403`; revert run 43288055753 passed)

---

## Phase 3: Release, Smoke-Check and Rollback Docs

### Changes Required

#### 1. `docs/RELEASE.md` (new)
Sections:
- **Release**: bump `version.py` → merge to `master` → `Build and Publish Docker Image` pushes `:latest` and `:<VERSION>` → record the current running digest (Phase 0 command) → `kubectl --context Legion-a6d6a7a -n legion-historic rollout restart deploy/rfhistoric-depl` (or delete the `rfhistoric-depl-*` pod) → `kubectl ... rollout status deploy/rfhistoric-depl`.
- **Post-release smoke check** (PowerShell, single-line commands, against the production URL): `/` 200; unauthenticated `/<db>/edelete/<id>` 403; `/<db>/dashboard`, `/<db>/metrics/<eid>`, `/<db>/compare` 200 for one real project; `kubectl logs` has no `Traceback`.
- **Rollback**: `kubectl --context Legion-a6d6a7a -n legion-historic set image deploy/rfhistoric-depl rfhistoric-app=proget.accruentsystems.com/qe_docker/library/rfhistoric:<previous VERSION>` (or `@sha256:<recorded digest>`), then rerun the smoke check. Note that `rollout undo` does not work while the deployment tracks `:latest`. Note that to return to `:latest` later, you `set image` back to `:latest` after a fixed release.
- **Dependency updates**: weekly grouped PR → `PR Build Check` must pass → merge → bump `version.py` in the same PR or a follow-up → release. Merge regularly; GitHub pauses Dependabot after prolonged inactivity.

#### 2. `README.md`
Add a short "Release and rollback" section linking `docs/RELEASE.md`.

### Success Criteria
- [x] Confirm the container name `rfhistoric-app` with `kubectl --context Legion-a6d6a7a -n legion-historic get deploy rfhistoric-depl -o jsonpath="{.spec.template.spec.containers[*].name}"` and correct the docs if it differs
- [x] Every command in `docs/RELEASE.md` is a single line and copy-paste runnable
- [ ] Peer review approves the PR (1 approval required)

Results (2026-11-12): container `rfhistoric-app` confirmed; pod label is `app=rfhistoric-app` (Phase 0 command corrected). Read-only doc commands run verbatim against production (`AccruentOne`, eid 961): `/`, dashboard, metrics, compare 200; `edelete` 403; 0 `Traceback` lines; digest command returns `sha256:977709c9…`. Restart/`set image` commands not executed (Phase 4).

**Pause for human confirmation before Phase 4.**

---

## Phase 4: Merge, Release and Admin Steps

### Steps
1. Merge the feature PR. Confirm `Build and Publish Docker Image` pushes `rfhistoric:0.3.0` and `:latest`.
2. Release per `docs/RELEASE.md`: restart the deployment, run the post-release smoke check, and record the new digest here.
3. Close #158, #159 and #160: `gh pr close <n> --comment "Superseded by #<feature PR> (QE-7618)"`.
4. Confirm `gh api repos/Accruent/robotframework-historic/dependabot/alerts --jq '.[] | select(.state=="open") | .number'` → empty (alerts #4 and #5 auto-close after the default-branch scan).
5. Branch protection (`neiljhowell` has repo admin, confirmed 2026-11-12): `gh api -X POST repos/Accruent/robotframework-historic/branches/master/protection/required_status_checks/contexts -f "contexts[]=build-and-smoke"`. If that returns 404 because no status-check block exists yet, use `gh api -X PATCH repos/Accruent/robotframework-historic/branches/master/protection/required_status_checks -F strict=false -f "contexts[]=build-and-smoke"`. Verify: `gh api repos/Accruent/robotframework-historic/branches/master/protection --jq '.required_status_checks.contexts'` → contains `build-and-smoke`.
6. Dependabot: merging the `dependabot.yml` change triggers a fresh version-update check, which should end the pause. Confirm on Insights → Dependency graph → Dependabot. Fallback: the "Resume" banner there, then "Check for updates". Then confirm the result → expect one grouped `pip-all` PR (or none if already current) and possibly one `actions-all` PR. Each shows `build-and-smoke`.
7. Update Confluence QA page 1336247055 "rfhistoric Documentation" (profile `qe-confluence`):
   - `:1` "on rancher" → AKS `legion-historic`.
   - `:43-44`, `:67-68`: verify the Bitbucket `accruent/ops_azure_ansible_k8` links resolve; fix or annotate them.
   - `:58-59`: "mysql in rancher" → Azure Database for MySQL 5.7.
   - "Building The Application": replace the manual `docker build` with GHA build/publish and link `docs/RELEASE.md` for release, smoke check and rollback.
8. Notify the `robotframework-historic-parser` owner about its `setuptools~=84.0.0` pin (alert #5 fix is 84.1.0).
9. Spin down this ticket's local stack: `docker compose -p qe-7618 down -v`.

### Success Criteria
- [ ] `rfhistoric:0.3.0` running in `legion-historic`; smoke check passes
- [ ] No open Dependabot PRs older than the current cycle; no open Dependabot alerts
- [ ] `build-and-smoke` required on `master`
- [ ] Dependabot resumed; at most one grouped PR per ecosystem per cycle
- [ ] Confluence page updated

---

## Testing Strategy
The repo has no unit test framework, and this plan does not add one (QE-7619 does). Coverage comes from local compose builds with PowerShell HTTP probes (Phase 1), the CI smoke job with a deliberate negative check (Phase 2), and the production post-release smoke check (Phase 4).

| Check | Where | Expected |
|---|---|---|
| Image builds on 3.14 | local + CI | success |
| `/` | local + CI + prod | 200 |
| dashboard / metrics / tmetrics / compare | local + CI + prod | 200 |
| Unauthenticated `edelete` | local + CI + prod | 403 |
| `import robot` in image | local | `ModuleNotFoundError` |
| Broken expectation | CI | check fails |

---

## Risks
- **Python 3.14 compatibility**: build and smoke verified pre-execution (see Current State). Fallback: `python:3.13` with the same plan.
- **Behaviour change in Flask on 3.14**: unlikely but possible deprecation output. Check the logs in Phase 1.
- **External `robotframework` consumers**: removal could break an unknown consumer that relies on the transitive install. Only the parser is known, and it declares its own dependency.
- **Required check blocks merges** if the runner, Docker Hub pulls or MySQL init is flaky. One local run never reached `db` (errno 99) and was not reproduced. The retry loop mitigates; on failure the workflow dumps `docker compose logs` (include `db`), and an admin can bypass (`enforce_admins: false`).
- **Dependabot PRs and secrets**: the workflow uses none, so Dependabot PRs run it normally.
- **`:latest` tracking**: rollback by tag only works if `version.py` is bumped on each release; the docs make this an explicit step.
- **Dependabot re-pause**: if grouped PRs are not merged, GitHub pauses it again. The cadence in `docs/RELEASE.md` addresses this.

## External Dependencies
- Jenkins access to confirm `pipeline.groovy` is unused (Phase 0).
- `kubectl` context `Legion-a6d6a7a` for the release and rollback docs check.
- ProGet access to confirm the tags.
- Confluence write access (`qe-confluence` profile).
- Coordination with QE-7619, which extends `pr-build.yml`.

---

## References
- Research: `.context/domains/dependency-management/research/current/2026-11-12-dependency-update-process.md`
- Publish workflow: `.github/workflows/build-and-publish.yml:3-58`
- Dependabot config: `.github/dependabot.yml:1-11`
- Dependencies: `requirements.txt:1-7`, `setup.py:8-9`, `setup.py:31`
- Base image: `Dockerfile:1`
- Version: `version.py:3`
- Smoke routes: `robotframework_historic/app.py:18-26`, `:146-204`, `:236-237`, `:327-354`, `:432-451`
- Seed data: `docker/init.sql`
- Linked test ticket: QE-7619
