---
date: 2026-11-12
author: Neil Howell
domain: dependency-management
jira: QE-7618
scope: ".github/dependabot.yml, .github/workflows/build-and-publish.yml, .github/workflows/release-drafter.yml, requirements.txt, setup.py, version.py, Dockerfile, docker-compose.yml, pipeline.groovy, robotframework_historic/app.py, robotframework_historic/args.py, README.md"
status: complete
---

# Research: Dependency Update Process
## Jira: QE-7618 — RF Historic | Dependency update process: Dependabot cadence, PR build check, open updates

### Research Question
What do we need to know to close QE-7618? Specifically: how Dependabot is configured, which dependencies are used at runtime and build time, which CI runs on PRs and on merge, how the image is built, tagged and started, and what exists for smoke checks and rollback.

### Summary
Dependabot runs `pip` updates daily with no `groups` block (`.github/dependabot.yml:1-11`), so each package gets its own PR. Three Dependabot PRs are open: #158 setuptools `~=82.0.1` -> `~=84.0.0`, #159 robotframework `~=7.4` -> `~=7.5`, and #160 pytz `~=2026.2` -> `~=2026.4`. `gh pr checks 158` reports no checks. The only GitHub Actions workflow that builds the image (`build-and-publish.yml`) runs on push to `master`, `workflow_dispatch`, or a merged PR. On an unmerged PR the job condition is false, so the job is skipped. It always pushes `:latest` and `:<version.py VERSION>`. At runtime only `pytz` from the ticket's list is imported (`app.py:6`). `robotframework` is not imported anywhere. `setuptools` is used only by `setup.py:1`, which `Dockerfile:10` runs through `pip install .`. The repo has no tests, no smoke-check docs, no rollback docs, and no container healthcheck. Two setuptools alerts are open: #4 Medium is fixed in 83.0.0 and #5 Low is fixed in 84.1.0. `~=84.0.0` resolves to `>=84.0.0,<84.1`, so #158 as written does not resolve alert #5. setuptools 83.0.0 and later require Python >=3.10, but `Dockerfile:1` is `python:3.9`. Branch protection on `master` requires 1 approving review and has no required status checks.

---

### Detailed Findings

#### 1. Ticket Context (from Jira)
- Status: Develop.
- Scope: merge or close #158/#159/#160 (#158 must be confirmed to resolve the open setuptools alerts). Remove `robotframework` instead if nothing needs it. Change the Dependabot schedule to weekly or monthly and add `groups`. Add a PR workflow that builds without pushing and starts the container. Document a post-release smoke check (`/` 200, unauthenticated `/<db>/edelete/<id>` 403, and the dashboard/metrics/compare pages load). Rollback is a redeploy of the previous image tag.
- AC: no unaddressed Dependabot PRs or alerts, at most one grouped PR per cycle, a PR build check that shows on every PR to master, and smoke and rollback steps documented in the repo.
- The ticket says the test workflow should run "the tests from the linked ticket" once they exist.

#### 1a. Open Dependabot Alerts (via `gh` as `neiljhowell`, 2026-11-12)
| # | Severity | Package | GHSA | Vulnerable | Fixed | Manifest |
|---|---|---|---|---|---|---|
| 4 | medium | setuptools | GHSA-h35f-9h28-mq5c | `< 83.0.0` | 83.0.0 | `requirements.txt` |
| 5 | low | setuptools | GHSA-xmj3-9gf7-h52w | `>= 38.2.2, < 84.1.0` | 84.1.0 | `requirements.txt` |
- #4: MANIFEST.in exclusion bypass in sdist via Unicode normalization collision (macOS APFS/HFS+).
- #5: Windows path escape via `namespace_packages.txt` during legacy wheel installation.
- PR #158 pins `~=84.0.0` (`>=84.0.0,<84.1`). This covers #4 but not #5.

#### 1b. Target Version Python Requirements (PyPI `requires_python`)
- setuptools 82.0.1: `>=3.9`. 83.0.0, 84.0.0, 84.1.0: `>=3.10`.
- pytz 2026.4: none declared. robotframework 7.5: `>=3.8`.
- `Dockerfile:1` base is `python:3.9`, so any setuptools version that fixes the alerts cannot be installed on the current base image.

#### 1c. Branch Protection — `master`
- `required_approving_review_count: 1`. No `required_status_checks`. `enforce_admins: false`.
- Interacting with the repo through `gh` requires the `neiljhowell` account (`gh auth switch -u neiljhowell`).

#### 1d. Dependabot Activity and Staleness (2026-11-12)
- Recent Dependabot PRs: #146 (2026-02-10, closed), #147-#151 (Feb-May, merged), #156 (2026-07-06, closed), #157 (2026-07-27, closed), #158 (2026-08-12, open), #159 (2026-09-17, open), #160 (2026-09-28, open). It has opened no PRs since 2026-09-28. The last merged Dependabot PR is #151 (2026-05-04).
- Latest on PyPI compared with the open PRs:

| Package | Pinned | Open PR | Latest PyPI |
|---|---|---|---|
| setuptools | `~=82.0.1` | `~=84.0.0` (#158) | 84.2.1 |
| pytz | `~=2026.2` | `~=2026.4` (#160) | 2026.6 |
| robotframework | `~=7.4` | `~=7.5` (#159) | 7.5.1 |
| Flask / bcrypt / flask-mysqldb / config | current | — | 3.1.3 / 5.0.0 / 2.0.0 / 0.5.1 (already latest) |

- The open PRs target versions that are already behind PyPI. Dependabot has not refreshed them since they were created.
- Cause (confirmed by repo owner): GitHub auto-paused Dependabot version updates because of inactivity (no Dependabot PRs merged since #151). It needs to be resumed in repo settings, and new PRs then need regular merging to keep it active.

#### 1e. Production Deployment (kubectl, context `Legion-a6d6a7a`, read-only)
- Namespace `legion-historic`: `rfhistoric-depl`, `historic-phpmyadmin-depl`, `owaspzaphistoric-depl`.
- `rfhistoric-depl` image `proget.accruentsystems.com/qe_docker/library/rfhistoric:latest`. Running digest is `sha256:977709c9e1f8dea971f1e0242b06aecbc6dc7c24be7ac78456bae52cf671daec`.
- `imagePullPolicy: Always`, strategy `RollingUpdate`, revision 11. The last restart was `kubectl.kubernetes.io/restartedAt: 2026-11-12T07:57:21-06:00`, so deploys are `kubectl rollout restart` pulling `:latest`.
- No deploy manifests exist in this repo. Per Confluence "rfhistoric Documentation" (QA space, page 1336247055), AKS config lives in Bitbucket `accruent/ops_azure_ansible_k8` at `sub_qa_automation/deployments/rfhistoric.yaml`, and ProGet pull access is in `sub_qa_automation/config-cluster.yaml`.
- The Confluence page records the Rancher-era manual setup (`docker build`, upload to ProGet). It does not mention Jenkins or `pipeline.groovy`. The groovy file appears to be a leftover from that pre-GHA era: its image path `qe_docker/rfhistoric` is not the one production pulls.
- Merging to master pushes `:latest` through GHA, but nothing in the repo or the deployment triggers a rollout. Current practice (confirmed by repo owner): delete the active `rfhistoric-depl-*` pod after a new image is published. The ReplicaSet recreates it and `imagePullPolicy: Always` pulls the new `:latest`. `kubectl rollout restart deploy/rfhistoric-depl -n legion-historic` is the equivalent rolling form, and the 2026-11-12 `restartedAt` annotation shows it has also been used.
- The deployment tracks `:latest`, so `kubectl rollout undo` returns to the same `:latest` tag and does not restore the previous image. Rollback means pointing the deployment at a specific `:<VERSION>` tag or digest (`kubectl set image`) or re-tagging `latest` in ProGet.

#### 1f. Linked Test Ticket — QE-7619 (Ready)
- "Add lightweight pytest coverage for routes, access control and delete flow."
- pytest + Flask `test_client` against the docker-compose MySQL seed (no mocks). `tests/conftest.py` with unauthenticated, viewer, and lead session helpers.
- Covers smoke 200s for every read-only page per seed DB, 403/allow access control, delete-flow integrity and idempotency, and schema/migration idempotency.
- It requires tests to run on every PR to master "using docker compose services in GitHub Actions" and to block the merge on failure.
- The two tickets overlap. QE-7618 adds the PR workflow (build + startup check) and QE-7619 adds pytest to it plus a required status check.

#### 2. Dependabot Configuration — `.github/dependabot.yml`
- `:3` `package-ecosystem: pip`, `:4` `directory: "/"`.
- `:5-8` schedule `interval: daily`, `time: "09:00"`, `timezone: US/Central`.
- `:9` `open-pull-requests-limit: 10`.
- `:10-11` `reviewers: [neiljhowell]`.
- No `groups`, `ignore`, `labels`, or `github-actions` ecosystem entries.
- `pip` ecosystem at `/` reads `requirements.txt` (and `setup.py`).

#### 3. Dependencies — `requirements.txt` / `setup.py`
- `requirements.txt:1-7`: `robotframework~=7.4`, `config~=0.5.1`, `Flask~=3.1.3`, `bcrypt~=5.0.0`, `flask-mysqldb~=2.0.0`, `pytz~=2026.2`, `setuptools~=82.0.1`.
- `setup.py:8-9` reads `requirements.txt` lines into `REQUIREMENTS`. `setup.py:31` `install_requires=REQUIREMENTS`. As a result, every line, `setuptools` and `robotframework` included, is installed into the runtime image.
- `setup.py:1` `from setuptools import find_packages, setup`. `setup.py:17` classifier `Framework :: Robot Framework` is metadata only.
- `setup.py:32-36` defines the console script `rfhistoric=robotframework_historic.app:main`.
- `version.py:3` `VERSION = "0.2.2"`.

#### 4. Runtime Imports
- `app.py:1-11`: `flask`, `flask_mysqldb`, `bcrypt`, `random`, `string`, `pytz` (`:6`), `datetime`, `logging`, `time`, `config` (`:10`), `.args`.
- `args.py:1`: `argparse`. `__init__.py` is empty.
- `robot`/`robotframework` is not imported anywhere in the repo. `setuptools` is imported only in `setup.py`.

#### 5. CI — GitHub Actions
- `.github/workflows/build-and-publish.yml`:
  - `:3-11` triggers: `push` to `master`, `pull_request` `types: [closed]` on `master`, `workflow_dispatch`.
  - `:22-26` job `if`: push, dispatch, or `pull_request.merged == true`. Unmerged PRs get no run, and opened/synchronize events do not trigger it at all.
  - `:13-14` `permissions: contents: read`.
  - `:33-37` reads `VERSION` from `version.py`.
  - `:39-44` ProGet login with `secrets.PROGET_USERNAME`/`PROGET_PASSWORD`.
  - `:46-52` `docker build` tagged `:latest` and `:<VERSION>`. `:54-58` pushes both to `proget.accruentsystems.com/qe_docker/library/rfhistoric`.
  - Merging Dependabot PRs without bumping `version.py` re-pushes the same `:<VERSION>` tag over the previous image.
- `.github/workflows/release-drafter.yml`: runs `release-drafter@v5.6.1` on push to `master`. Config is in `.github/release-drafter.yml`.
- Dependabot-triggered workflows receive no repository Actions secrets by default (GitHub behaviour). A build-only PR job needs no ProGet secret.

#### 6. CI — Jenkins `pipeline.groovy`
- Stages: checkout, build `proget.accruentsystems.com/qe_docker/rfhistoric`, commented-out "Test image", then push `${BUILD_NUMBER}` and `latest` with credential `svcselenium`.
- Registry path differs from GHA (`qe_docker/rfhistoric` vs `qe_docker/library/rfhistoric`). The repo does not show whether this pipeline is still active.

#### 7. Image and Startup
- `Dockerfile:1` `FROM python:3.9`. `:8-10` `COPY . /app`, `pip install .`. `:13` `EXPOSE 5000`.
- `Dockerfile:18` `CMD rfhistoric -s "${SQLHOST}" -t "${PORT}" -u "${USERNAME}" -p "${PASSWORD}" -a "${FLASKHOST}"`.
- `app.py:543-558` `main()`: sets `MYSQL_*` config from args, random `secret_key`, `app.run(host=args.apphost)` (Flask dev server, port 5000).
- `flask_mysqldb` connects lazily, so the process can start without a DB. `/` queries `robothistoric.TB_PROJECT` (`app.py:18-26`), so a 200 on `/` needs a reachable DB.
- `docker-compose.yml`: `db` (`mysql:5.7`, `./docker/init.sql` seed), `phpmyadmin` (8081), `rfhistoric` (5001->5000, env `SQLHOST=db`, `PORT=3306`, `USERNAME=root`, `PASSWORD=password`, `FLASKHOST=0.0.0.0`). It defines no healthchecks. `depends_on` only orders startup.
- `docker/init.sql` seeds the projects `rf_full_data`, `roomba_sync_data`, `empty_project` (see QE-7617 research).

#### 8. Smoke-Check Target Routes — `app.py`
- `/` `:18-26` public.
- `/<db>/dashboard` `:146-204` public.
- `/<db>/metrics/<eid>` `:341-354` public. `/<db>/tmetrics` `:327-339` public.
- `/<db>/compare` `:432-451` public.
- `/<db>/edelete/<eid>` `:236-325`. The guard `:237` returns `'Forbidden', 403` when `role != 'lead'`, before any DB call.
- Existing manual verification snippets (PowerShell `Invoke-WebRequest` against `localhost:5001`) are in `.github/copilot-instructions.md`.

#### 9. Tests, Docs, Rollback
- The repo has no `tests/` directory, `*test*.py` files, `.robot` suites, pytest or tox config.
- `README.md` covers install and usage only (`:20-67`). It has no deploy, release, smoke, or rollback sections.
- Only schema rollback scripts exist (`scripts/rollback_qe7360.py`, `scripts/rollback_qe7617.py`). The repo has no image rollback procedure.
- Production runs in K8s namespace `legion-historic` (QE-7617 research). The repo contains no K8s manifests, so the deployed tag and redeploy mechanism are not visible here.

---

### Code References
- `.github/dependabot.yml:1-11` - pip ecosystem, daily schedule, PR limit 10, reviewer
- `.github/workflows/build-and-publish.yml:3-11` - triggers (push/merged PR/dispatch)
- `.github/workflows/build-and-publish.yml:22-26` - merged-only job condition
- `.github/workflows/build-and-publish.yml:46-58` - build + push `:latest` and `:<VERSION>`
- `.github/workflows/release-drafter.yml` - release notes draft on master push
- `requirements.txt:1-7` - pinned deps incl. robotframework, setuptools, pytz
- `setup.py:1` - setuptools import (build time)
- `setup.py:8-9`, `setup.py:31` - requirements.txt -> install_requires
- `setup.py:32-36` - `rfhistoric` console script
- `version.py:3` - image version tag source
- `robotframework_historic/app.py:6` - only runtime pytz import
- `robotframework_historic/app.py:18-26` - `/` index (DB query)
- `robotframework_historic/app.py:236-237` - `edelete` route and lead guard
- `robotframework_historic/app.py:543-558` - `main()` / Flask dev server
- `Dockerfile:1`, `Dockerfile:10`, `Dockerfile:18` - base image, `pip install .`, CMD
- `docker-compose.yml` - local db + app stack, no healthchecks
- `pipeline.groovy` - Jenkins build/push (BUILD_NUMBER + latest), test stage commented out

### Architecture Patterns
- One `requirements.txt` serves as both runtime and install metadata through `setup.py`. Build-only and runtime deps are not separated.
- The image is published only after merge to `master`. Tags are `latest` + `version.py` value. Version bumps are manual.
- Release notes are drafted by release-drafter. Publishing is manual.
- Auth guards are inline `session.get('role') != 'lead'` checks that return 403 before DB access.
- Verification is manual (PowerShell HTTP probes in `.github/copilot-instructions.md`).

### Constraints Discovered
- No PR-time workflow exists. A build check on PRs needs a new trigger (`pull_request` opened/synchronize), separate from the merged-only publish job.
- Starting the container standalone has no DB. `/` needs MySQL, so an "app comes up" check either brings up the compose `db` service or checks a route that does not touch the DB (e.g. the `edelete` 403 guard or `/login` GET).
- Compose has no healthcheck. MySQL readiness after `up` is not signalled.
- Dependabot PRs run without Actions secrets, so a PR build check must not need ProGet credentials.
- `setuptools` is both a build-time import (`setup.py`) and an installed runtime requirement through `install_requires`.
- Removing `robotframework` from `requirements.txt` also removes it from `install_requires`. Nothing in the repo imports it, but external users of the PyPI package might expect it.
- Python 3.9 base image: setuptools >=83 requires Python >=3.10, so the alert fixes need a base image change. pytz 2026.4 and robotframework 7.5 install on 3.9.
- `~=84.0.0` (PR #158) excludes 84.1.0, which is the fix version for alert #5.
- `master` has no required status checks. A new PR check is visible but not enforced unless branch protection is updated.
- Re-merging without a `version.py` bump overwrites the `:<VERSION>` tag. This limits "redeploy previous tag" rollback to tags that were not overwritten.
- No tests exist to run in the PR workflow yet ("tests from the linked ticket" are pending).

### Potential Approaches
- **Rollback**: `kubectl set image deploy/rfhistoric-depl rfhistoric-app=proget.accruentsystems.com/qe_docker/library/rfhistoric:<previous VERSION or @digest> -n legion-historic`, or re-tag `latest` in ProGet and `kubectl rollout restart`. Record the running digest before each release.
- **Confluence updates (include in the plan)**: Confluence QA page 1336247055 "rfhistoric Documentation":
  - `:1` describes setup "on rancher". Production is AKS `legion-historic`.
  - `:43-44`, `:67-68` link Bitbucket `accruent/ops_azure_ansible_k8`. No GitHub `Accruent/ops_azure_ansible_k8` exists, so the links are possibly still valid; verify they are current.
  - `:58-59` describe the parser `.bat` on the Jenkins master "to match mysql in rancher". Production DB is Azure Database for MySQL 5.7.44.
  - "Building The Application" covers only a manual `docker build`. The page has no GHA build/publish, no `:latest` + rollout restart deploy step, and no smoke check or rollback. Add these, or link to the in-repo docs created by this ticket.
- **Stale PRs**: close #158/#159/#160 and let a regrouped Dependabot config raise one fresh PR, or bump `requirements.txt` directly to current PyPI versions.
- **Base image**: `python:3.9` -> `python:3.10`+ (Debian-based, so the same build path). All pinned deps support 3.10+. QE-7619's pytest work then runs against the new base.
- **setuptools alerts**: change the pin to `~=84.1` or `>=84.1.0` and move `Dockerfile:1` to `python:3.10`+. Alternatively, move setuptools out of `requirements.txt` (build-only) and dismiss the alerts with a justification.
- **Open PRs**: merge #158/#160 after a local `docker compose build` + smoke check. For #159, either merge it or close it and remove `requirements.txt:1`.
- **Dependabot**: set `interval: weekly` or `monthly` and add `groups: { pip-all: { patterns: ["*"] } }` (optionally split by `update-types`). Optionally add a `github-actions` ecosystem entry.
- **PR build check**: new workflow on `pull_request` (`opened`, `synchronize`, `reopened`) to `master` that runs `docker build` without push. Then either `docker compose up -d` and probe routes, or `docker run` the image alone and probe a non-DB route. Result appears as a PR check. Branch protection can make it required.
- **Smoke/rollback docs**: a README section or `docs/` file listing the probes (`/` 200, unauthenticated `/<db>/edelete/<id>` 403, dashboard/metrics/compare 200) based on the existing PowerShell snippets, plus redeploying the previous ProGet tag in `legion-historic`.

### Open Questions
- Is `pipeline.groovy` safe to delete? Confluence does not reference it, and production pulls the GHA image path. Confirm no Jenkins job still points at it.
- Does the base image move to Python 3.10 (minimum) or a newer version? Scope decision: in scope if it does not drastically increase LOE.
- Should the new PR build check be added as a required status check on `master`? (QE-7619 requires its tests to block merge.)
- Does anything outside this repo (the parser/listener tools) depend on `robotframework-historic` installing `robotframework`?
