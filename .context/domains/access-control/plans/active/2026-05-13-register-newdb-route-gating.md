---
date: 2026-05-13
author: Neil Howell
domain: access-control
jira: QE-7371
research: .context/domains/access-control/research/current/2026-05-13-register-newdb-route-gating.md
status: complete
phases: 2
---

# QE-7371: Gate Register and New-Project Routes to Lead Role Only — Implementation Plan

## Overview
Close the privilege escalation paths left by QE-7360: add route-level Lead-only guards to `GET /register`, `POST /register`, `GET /newdb`, and `POST /newdb`, then update the corresponding nav links in `index.html` and the form guard in `register.html` to hide those actions from non-Lead users.

---

## Current State Analysis

*(Full details in research artifact. Key facts for implementation:)*

- `GET /register` and `POST /register` (`app.py:69–80`): no session or role check at route level. Template wraps form in `{% if session['name'] %}` — UI-only, bypassed by direct HTTP request. A Viewer navigating to `/register` sees the form and can create a Lead account.
- `GET /newdb` and `POST /newdb` (`app.py:82–152`): no session or role check. Template has no auth guard at all. Accessible to unauthenticated users.
- `index.html:55`: "New User" link rendered inside `{% if session['name'] %}` — shown to all authenticated users (viewer + lead).
- `index.html:59`: "New Project" link rendered **outside** all auth blocks — shown to everyone including unauthenticated.
- QE-7360 guard pattern: `if session.get('role') != 'lead': return 'Forbidden', 403` — first statement in handler body. Used in `delete_db_conf` (`app.py:24`) and `delete_db` (`app.py:29`).
- QE-7360 template pattern: `{% if session.get('role') == 'lead' %}` — used in `index.html:92` and `ehistoric.html:106`.

---

## Desired End State

- `GET /register` returns 403 for any caller whose `session.get('role') != 'lead'` (Viewer and unauthenticated)
- `POST /register` returns 403 for any caller whose `session.get('role') != 'lead'`
- `GET /newdb` returns 403 for any caller whose `session.get('role') != 'lead'`
- `POST /newdb` returns 403 for any caller whose `session.get('role') != 'lead'`
- "New User" nav link in `index.html` is visible only to Lead users
- "New Project" nav link in `index.html` is visible only to Lead users
- `register.html` form guard uses `session.get('role') == 'lead'` (consistent with QE-7360 template style)
- Logout button in `index.html` is unaffected — still shown to all authenticated users
- No schema changes; no migration scripts required

---

## What We're NOT Doing

- Not introducing a new `admin` role — deferred pending real-world usage of Lead role (recorded in DOMAIN.md)
- Not adding a styled 403 error page — plain-text `'Forbidden', 403` matches QE-7360 precedent
- Not wrapping `newdb.html` body in a role guard — route-level enforcement is sufficient
- Not extracting a shared `require_lead()` helper or decorator — inline pattern is the established convention
- Not modifying any deletion routes, dashboard, or test result views

---

## Implementation Approach

Two sequential phases. Phase 1 is the security fix (route-level enforcement); it is independently verifiable and deployable. Phase 2 is the UI cleanup (template guards); it has no security impact but prevents confusing UI for Viewer users. Phase 2 depends on Phase 1 being complete only in that Phase 1 is the more critical change — the phases could be swapped safely, but this order is preferred.

---

## Phase 1: Route-Level Guards

### Overview
Add `if session.get('role') != 'lead': return 'Forbidden', 403` as the first statement in each of the four unguarded handlers. This is the complete security fix.

### Changes Required

#### 1. `register` route — GET and POST
**File:** `robotframework_historic/app.py`  
**Current (`app.py:69–72`):**
```python
@app.route('/register', methods=["GET", "POST"])
def register():
    if request.method == 'GET':
        return render_template("register.html")
```
**Change:** Add role guard as first statement in the function body, before the method check:
```python
@app.route('/register', methods=["GET", "POST"])
def register():
    if session.get('role') != 'lead':
        return 'Forbidden', 403
    if request.method == 'GET':
        return render_template("register.html")
```
A single guard at the top covers both GET and POST — matches how `delete_db_conf` handles a single-method route and how `delete_db` rejects before any DB interaction.

#### 2. `add_db` route — GET and POST
**File:** `robotframework_historic/app.py`  
**Current (`app.py:82–84`):**
```python
@app.route('/newdb', methods=['GET', 'POST'])
def add_db():
    if request.method == "POST":
```
**Change:** Add role guard as first statement in the function body:
```python
@app.route('/newdb', methods=['GET', 'POST'])
def add_db():
    if session.get('role') != 'lead':
        return 'Forbidden', 403
    if request.method == "POST":
```

### Success Criteria

#### Automated Verification
- [x] App starts without error: `python -m flask run` (or Docker equivalent)
- [x] `GET /register` as unauthenticated returns 403 (curl or requests without session)
- [x] `POST /register` as unauthenticated returns 403
- [x] `GET /newdb` as unauthenticated returns 403
- [x] `POST /newdb` as unauthenticated returns 403

#### Manual Verification
- [x] Log in as Viewer (`role='viewer'`): navigate to `/register` in browser → plain "Forbidden" page, HTTP 403
- [x] Log in as Viewer: navigate to `/newdb` in browser → plain "Forbidden" page, HTTP 403
- [x] Log in as Lead (`role='lead'`): navigate to `/register` → register form renders normally
- [x] Log in as Lead: navigate to `/newdb` → new project form renders normally
- [x] Log in as Lead: submit register form with a new Viewer user → user created, redirects to index
- [x] Log in as Lead: submit new project form → project created, appears on index
- [x] All existing non-auth functionality unaffected (dashboard, ehistoric, metrics views load normally as any role)

**Pause here for human confirmation of manual verification before proceeding to Phase 2.**

---

## Phase 2: Template UI Guards

### Overview
Update nav links in `index.html` and the form wrapper in `register.html` to hide Lead-only actions from Viewer and unauthenticated users. This is UI polish that prevents confusing affordances — the route guards from Phase 1 remain the security enforcement layer.

### Changes Required

#### 1. `index.html` — "New User" nav link
**File:** `robotframework_historic/templates/index.html`

The "New User" link currently shares its enclosing `{% if session['name'] %}` block with the Logout button. The outer block condition cannot change (Logout must still appear for Viewers). Add a nested `{% if session.get('role') == 'lead' %}` around the link only.

**Current (`index.html:52–60`):**
```html
{% if session['name'] %}
<a class="btn btn-light text-primary" type=button href="/logout"> <i class="fa fa-sign-out"></i><b>Logout</b></a>
<a class="btn btn-light text-primary" type=button href="/register"><i class="fa fa-plus-circle"></i> <b>New User</b></a>
{% else %}
<a class="btn btn-light text-primary" type=button href="/login"><i class="fa fa-user-circle"></i> <b>Login</b></a>
{% endif %}
<a class="btn btn-light text-primary" type=button href="/newdb"><i class="fa fa-plus-circle"></i> <b>New Project</b></a>
```

**After:**
```html
{% if session['name'] %}
<a class="btn btn-light text-primary" type=button href="/logout"> <i class="fa fa-sign-out"></i><b>Logout</b></a>
{% if session.get('role') == 'lead' %}
<a class="btn btn-light text-primary" type=button href="/register"><i class="fa fa-plus-circle"></i> <b>New User</b></a>
{% endif %}
{% else %}
<a class="btn btn-light text-primary" type=button href="/login"><i class="fa fa-user-circle"></i> <b>Login</b></a>
{% endif %}
{% if session.get('role') == 'lead' %}
<a class="btn btn-light text-primary" type=button href="/newdb"><i class="fa fa-plus-circle"></i> <b>New Project</b></a>
{% endif %}
```

#### 2. `register.html` — form wrapper guard
**File:** `robotframework_historic/templates/register.html`

**Current (`register.html:51`):**
```html
{% if session['name'] %}
```
**After:**
```html
{% if session.get('role') == 'lead' %}
```
Aligns with QE-7360 template style (`session.get()` safe access, explicit role check).

### Success Criteria

#### Manual Verification
- [x] Not logged in: neither "New User" nor "New Project" buttons appear on index page
- [x] Logged in as Viewer: Logout button visible; "New User" and "New Project" buttons not visible
- [x] Logged in as Lead: Logout, "New User", and "New Project" buttons all visible
- [x] Logged in as Viewer: navigate to `/register` directly → blank page (form hidden by template guard) AND HTTP 403 from route guard (Phase 1)
- [x] Logged in as Lead: `/register` page renders register form as expected
- [x] Login/Logout flow unaffected for all roles

---

## Testing Strategy

### Manual Test Matrix

| Scenario | `/register` GET | `/newdb` GET | "New User" button | "New Project" button |
|---|---|---|---|---|
| Unauthenticated | 403 | 403 | hidden | hidden |
| Authenticated, Viewer | 403 | 403 | hidden | hidden |
| Authenticated, Lead | 200 (form) | 200 (form) | visible | visible |

### Regression Checks
- Dashboard, ehistoric, metrics, flaky, search, compare views: all load for Viewer and Lead
- Delete test run (`/<db>/deleconf/<eid>`) and delete project (`/<db>/deldbconf`): still return 403 for Viewer (QE-7360 behaviour unchanged)
- Login / Logout flows: unaffected

---

## Deployment

No schema changes — no migration script required.

### Steps
1. Push feature branch to origin (complete)
2. Raise PR against `master` on GitHub
3. PR review and approval
4. Merge PR into `master`
5. Jenkins auto-triggers on merge: builds Docker image tagged `proget.accruentsystems.com/qe_docker/rfhistoric`, pushes `{BUILD_NUMBER}` and `latest` tags to ProGet
6. Deploying host pulls new `latest` image and restarts the container

### Post-Deployment Smoke Check
- Unauthenticated: `GET /register` and `GET /newdb` return 403
- Lead: `/register` and `/newdb` render forms normally
- Nav bar: "New User" and "New Project" buttons visible only when logged in as Lead

---

## References
- Research: `.context/domains/access-control/research/current/2026-05-13-register-newdb-route-gating.md`
- QE-7360 guard precedents: `robotframework_historic/app.py:24`, `app.py:29`
- QE-7360 template precedents: `robotframework_historic/templates/index.html:92`, `templates/ehistoric.html:106`
