# GitHub Copilot Instructions — robotframework-historic

## Application Overview

RFHistoric is a Flask-based web application for viewing and managing Robot Framework test execution history. It stores results in MySQL and exposes a UI on port 5000 (mapped to 5001 in local Docker Compose).

**Most users access the application unauthenticated.** Viewing dashboards, metrics, flaky test reports, and test comparisons requires no login. Only administrative actions (creating users, creating projects, deleting runs/projects) are restricted to the Lead role.

---

## Role Definitions

| Role | `session.get('role')` | Permitted actions |
|---|---|---|
| **Unauthenticated** | `None` | View all dashboards, metrics, flaky reports, comparisons, test history |
| **Viewer** | `'viewer'` | Same as unauthenticated — no additional capabilities beyond login/logout |
| **Lead** | `'lead'` | Everything above + create users (`/register`), create projects (`/newdb`), delete test runs, delete projects |

> `viewer` and unauthenticated have identical access to content. The only difference is a session exists. All meaningful permission boundaries are between "not Lead" and "Lead".

---

## Auth Model

- Flask session-based auth — no Flask-Login, no decorators
- `session.get('role')` returns `None` when unauthenticated, `'viewer'` for standard logged-in users, `'lead'` for admins
- Route guard pattern (established in QE-7360):
  ```python
  if session.get('role') != 'lead':
      return 'Forbidden', 403
  ```
- Template guard pattern:
  ```html
  {% if session.get('role') == 'lead' %}
  ```
- The `!= 'lead'` check correctly blocks both unauthenticated and viewer sessions — no separate unauthenticated check needed

---

## Testing Conventions

### Access Control Changes
Test in this priority order:

1. **Unauthenticated (highest priority)** — no session cookie; this is the most common real-world user type. Guarded routes must return 403. Publicly accessible routes must continue to work.
2. **Authenticated Viewer** — logged in with `role = 'viewer'`; guarded routes must return 403.
3. **Authenticated Lead** — logged in with `role = 'lead'`; guarded routes must return the intended response (form, redirect, etc.).

> Unauthenticated verification is mandatory before committing any auth change. Viewer and Lead checks are also required but secondary.

### Automated Verification (PowerShell)

```powershell
# 1. Unauthenticated — guarded routes return 403
try { Invoke-WebRequest http://localhost:5001/some-route -Method GET }
catch { $_.Exception.Response.StatusCode.value__ }  # expect 403

# 2. Public routes still work unauthenticated — expect 200
(Invoke-WebRequest http://localhost:5001/ -Method GET).StatusCode

# 3. Viewer session — guarded routes return 403
$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
Invoke-WebRequest http://localhost:5001/login -Method POST `
    -Body @{ username = 'viewer_user'; password = 'password' } `
    -SessionVariable session | Out-Null
try { Invoke-WebRequest http://localhost:5001/some-route -Method GET -WebSession $session }
catch { $_.Exception.Response.StatusCode.value__ }  # expect 403

# 4. Lead session — guarded routes return 200
$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
Invoke-WebRequest http://localhost:5001/login -Method POST `
    -Body @{ username = 'lead_user'; password = 'password' } `
    -SessionVariable session | Out-Null
(Invoke-WebRequest http://localhost:5001/some-route -Method GET -WebSession $session).StatusCode  # expect 200
```

### Manual Verification Checklist (for auth changes)
UI state that cannot be verified via HTTP status codes alone:
- [ ] Open `http://localhost:5001/` without logging in — confirm **New User** and **New Project** buttons are not visible in the nav bar
- [ ] Log in as a Viewer — confirm **New User** and **New Project** buttons are still not visible in the nav bar
- [ ] Log in as a Lead — confirm **New User** and **New Project** buttons **are** visible in the nav bar

---

## Docker Compose (Local Development)

```
Service        Port      Purpose
db             (internal) MySQL 5.7 — accounts db
phpmyadmin     8081       DB admin UI
rfhistoric     5001→5000  Flask app
```

Rebuild and restart after code changes:
```bash
docker compose build rfhistoric && docker compose up -d rfhistoric
```

---

## Codebase Conventions

- All route handlers are in `robotframework_historic/app.py`
- Templates are in `robotframework_historic/templates/`
- Schema migration scripts are in `scripts/` (no migration framework — manual execution required)
- Context/planning artifacts are in `.context/domains/{domain}/` — these are development artifacts and are not required at runtime
