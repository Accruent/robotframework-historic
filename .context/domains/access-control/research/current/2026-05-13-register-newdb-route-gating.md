---
date: 2026-05-13
author: Neil Howell
domain: access-control
jira: QE-7371
scope: "robotframework_historic/app.py, robotframework_historic/templates/register.html, robotframework_historic/templates/newdb.html, robotframework_historic/templates/index.html"
status: validated
---

# Research: Register and New-Project Route Gating to Lead Role
## Jira: QE-7371 — RFHistoric: Gate register and new-project routes to Lead role only

### Research Question
What is the current state of the `/register` and `/newdb` routes — their implementation, authentication/authorization handling, template-side controls, and the role-based access patterns established by QE-7360 — such that both routes can be gated to Lead role only (route-level 403 + UI hiding)?

### Summary
Both `/register` and `/newdb` currently lack route-level authorization checks, creating privilege escalation paths that survive the role-based deletion guards added in QE-7360. The `/newdb` GET/POST routes are fully open to unauthenticated requests. The `/register` GET/POST routes rely exclusively on a template-side `{% if session['name'] %}` guard, which a direct HTTP client bypasses trivially. QE-7360 established a consistent guard pattern (`if session.get('role') != 'lead': return 'Forbidden', 403`) used in two deletion routes; that same pattern is the correct fix here. Index.html's "New User" nav link is shown to all authenticated users; the "New Project" nav link is shown to all users including unauthenticated.

---

### Detailed Findings

#### 1. `/register` Route — Current State

**Route Handler (`app.py:69–80`):**
```python
@app.route('/register', methods=["GET", "POST"])
def register():
    if request.method == 'GET':
        return render_template("register.html")
    else:
        name = request.form['name']
        email = request.form['email']
        password = request.form['password'].encode('utf-8')
        role = request.form.get('role', 'viewer')
        hash_password = bcrypt.hashpw(password, bcrypt.gensalt())
        cur = mysql.connection.cursor()
        use_db(cur, "accounts")
        cur.execute("INSERT INTO TB_USERS (name, email, password, role) VALUES (%s,%s,%s,%s)", ...)
        mysql.connection.commit()
        session['name'] = request.form['name']
        session['email'] = request.form['email']
        return redirect(url_for('index'))
```

- **GET**: No session or role check. Renders `register.html` to any caller including unauthenticated users.
- **POST**: No session or role check. Inserts a new row into `accounts.TB_USERS` with caller-supplied `role` field. Also sets `session['name']` and `session['email']` — but does **not** set `session['role']`, so the auto-logged-in registrant cannot delete, but they have a new account at whatever role they specified in the form.
- The `role` field accepted by POST is a free-form select input (see template below); a raw HTTP POST could supply any value.

**Template (`register.html:51`):**
```html
{% if session['name'] %}
<div id="db">
  ...
  <form ... method="post">
    ...
    <select name="role" id="role">
      <option value="viewer" selected>Viewer</option>
      <option value="lead">Lead</option>
    </select>
    ...
  </form>
</div>
{% endif %}
```

- The entire form is wrapped in `{% if session['name'] %}` — so an unauthenticated browser visit renders a blank page.
- However, this is a UI-only guard. A direct `GET /register` returns HTTP 200 to unauthenticated requests. A direct `POST /register` with form fields succeeds for anyone.
- A Viewer who navigates to `/register` while logged in sees the full form and can create a Lead account.

---

#### 2. `/newdb` Route — Current State

**Route Handler (`app.py:82–152`):**
```python
@app.route('/newdb', methods=['GET', 'POST'])
def add_db():
    if request.method == "POST":
        db_name = request.form['dbname']
        ...
        cursor.execute("Create DATABASE %s;" % db_name)
        cursor.execute("INSERT INTO robothistoric.TB_PROJECT ...")
        ...
        return redirect(url_for('index'))
    else:
        return render_template('newdb.html')
```

- **GET**: No session or role check. Renders `newdb.html` to any caller including unauthenticated users.
- **POST**: No session or role check. Executes `CREATE DATABASE` and inserts into `TB_PROJECT`. Available to any caller including unauthenticated users.

**Template (`newdb.html`):**
- No `{% if session['name'] %}` or role guard of any kind.
- Form is always rendered and always functional in the browser.

---

#### 3. `index.html` Navigation Links

**Relevant nav block (`index.html:52–60`):**
```html
<li class="nav-item">
    {% if session['name'] %}
    <a class="btn btn-light text-primary" href="/logout">...</a>
    <a class="btn btn-light text-primary" href="/register">... <b>New User</b></a>
    {% else %}
    <a class="btn btn-light text-primary" href="/login">...</a>
    {% endif %}
    <a class="btn btn-light text-primary" href="/newdb">... <b>New Project</b></a>
</li>
```

- **"New User" link** (`index.html:55`): Inside `{% if session['name'] %}` — shown to all authenticated users regardless of role (viewer + lead both see it).
- **"New Project" link** (`index.html:59`): **Outside** the auth block — shown to **all** users including unauthenticated.

---

#### 4. QE-7360 Established Auth Pattern

**Route-level guard (2 instances):**
```python
# app.py:24 — delete_db_conf
@app.route('/<db>/deldbconf', methods=['GET'])
def delete_db_conf(db):
    if session.get('role') != 'lead':
        return 'Forbidden', 403
    return render_template('deldbconf.html', db_name=db)

# app.py:29 — delete_db
@app.route('/<db>/delete', methods=['GET'])
def delete_db(db):
    if session.get('role') != 'lead':
        return 'Forbidden', 403
    ...
```

- Pattern: `if session.get('role') != 'lead': return 'Forbidden', 403`
- Placed as the **first statement** in the route handler body, before any DB interaction.
- Uses `session.get('role')` (safe dict access, returns `None` for unauthenticated rather than raising `KeyError`).
- Returns plain-text `'Forbidden'` with HTTP status 403.

**Template-level guard (2 instances):**
```html
<!-- index.html:92 — Delete Project button -->
{% if session.get('role') == 'lead' %}
<a href="{{item[1]}}/deldbconf" class="btn btn-danger ...">Delete</a>
{% endif %}

<!-- ehistoric.html:106 — Delete test run link -->
{% if session.get('role') == 'lead' %} | <a href="./deleconf/...">Delete</a>{% endif %}
```

- Pattern: `{% if session.get('role') == 'lead' %}` to conditionally render the UI control.

---

#### 5. User/Role Model

**Schema (`docker/init.sql:17–22`):**
```sql
CREATE TABLE IF NOT EXISTS TB_USERS (
    id       INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    name     VARCHAR(255),
    email    VARCHAR(255),
    password VARCHAR(255),
    role     VARCHAR(20) NOT NULL DEFAULT 'viewer'
);
```

- Two in-use role values: `'lead'` and `'viewer'` (default).
- Seed row: `admin@local` with role `'lead'`.

**Session variables set at login (`app.py:47–50`):**
```python
session['name'] = user['name']
session['email'] = user['email']
session['role'] = user['role']
```

- `session['role']` is set for authenticated users from the DB value.
- `session.get('role')` returns `None` for unauthenticated sessions (no `KeyError`).
- The register POST handler (`app.py:78–79`) sets `session['name']` and `session['email']` but **does not set `session['role']`** — a newly self-registered user is auto-logged-in but without a role in their session until they log out and back in.

---

### Code References

| File | Lines | Description |
|---|---|---|
| `robotframework_historic/app.py` | 24–26 | `delete_db_conf` — Lead role guard (QE-7360 pattern) |
| `robotframework_historic/app.py` | 29–32 | `delete_db` — Lead role guard (QE-7360 pattern) |
| `robotframework_historic/app.py` | 37–51 | `login` — sets `session['role']` from DB |
| `robotframework_historic/app.py` | 69–80 | `register` — no auth/role guard, accepts any role |
| `robotframework_historic/app.py` | 82–152 | `add_db` (`/newdb`) — no auth/role guard |
| `robotframework_historic/templates/register.html` | 51 | `{% if session['name'] %}` — UI-only guard, bypassed by direct request |
| `robotframework_historic/templates/newdb.html` | 1–120 | No auth guard anywhere in template |
| `robotframework_historic/templates/index.html` | 52–60 | Nav links: "New User" gated by `session['name']`, "New Project" ungated |
| `robotframework_historic/templates/index.html` | 92–94 | Delete button: `{% if session.get('role') == 'lead' %}` (QE-7360 pattern) |
| `robotframework_historic/templates/ehistoric.html` | 106 | Delete link: `{% if session.get('role') == 'lead' %}` (QE-7360 pattern) |
| `docker/init.sql` | 17–22 | `TB_USERS` schema — `role VARCHAR(20) NOT NULL DEFAULT 'viewer'` |

---

### Architecture Patterns

- **No decorator-based auth** (Flask-Login not used). All auth enforcement is ad-hoc per-route.
- **Route guard pattern (QE-7360):** `if session.get('role') != 'lead': return 'Forbidden', 403` as first statement in handler. Applied to both GET and mutating routes independently.
- **Template guard pattern (QE-7360):** `{% if session.get('role') == 'lead' %}` wraps UI controls that trigger Lead-only actions.
- **`session.get()` vs `session[]`:** The codebase uses `.get()` in route guards (safe for unauthenticated) but `session['name']` in older template checks (raises `UndefinedError` in Jinja2 if session key absent — works only because Jinja2 treats undefined as falsy, not a Python `KeyError`).

---

### Constraints Discovered

1. **No `@login_required` abstraction exists.** Each route that needs auth must inline the check.
2. **`register` POST auto-logs-in the registrant** (sets `session['name']`, `session['email']`) but does not set `session['role']`. After the guard is added, a valid Lead who self-registers will be redirected to index without a role in session — a minor inconsistency to consider, but out of scope since Lead-only registration means the caller is already Lead.
3. **`newdb.html` has no `{% if %}` wrapper** — adding a guard requires either a wrapper or rendering a 403 page. The QE-7360 precedent uses a plain-text `'Forbidden', 403` response (no template).
4. **`register.html` guard uses `{% if session['name'] %}` (string key lookup), not `session.get()`** — changing this to `{% if session.get('role') == 'lead' %}` is a non-breaking improvement that aligns with QE-7360 template style.
5. **`index.html` "New Project" link** is outside the `{% if session['name'] %}` block — moving it inside and further restricting to Lead changes the visual layout slightly (the button disappears for all non-Lead users).

---

### Potential Approaches

These are options that exist given the codebase as-is, not recommendations:

**Route guards:** Apply `if session.get('role') != 'lead': return 'Forbidden', 403` to the top of all four handlers — `register` GET, `register` POST, `add_db` GET, `add_db` POST. This mirrors the pattern in `delete_db_conf` and `delete_db` exactly.

**Template guard — `register.html`:** Replace `{% if session['name'] %}` with `{% if session.get('role') == 'lead' %}` to align with QE-7360 style and prevent the Lead form from appearing to Viewer users.

**Template guard — `index.html` "New User" link:** Wrap with `{% if session.get('role') == 'lead' %}` instead of the current `{% if session['name'] %}`. Currently shares the same `<li>` block as Logout; the guard can be narrowed to role without restructuring the block.

**Template guard — `index.html` "New Project" link:** Move inside a `{% if session.get('role') == 'lead' %}` block. Currently outside any auth block — requires adding a new conditional around that anchor tag.

**`newdb.html` template guard:** Could wrap in `{% if session.get('role') == 'lead' %}` similar to `register.html`, but route-level guard is sufficient for security; template guard is UI polish only.

---

### Open Questions

*All resolved during research review — no blockers for planning.*

1. ~~Should the `register` POST handler also set `session['role']` after inserting the new user?~~ **Resolved: non-issue.** After the gate is added, the caller is already Lead and already has `session['role'] == 'lead'` in their session from their own login. The POST sets `session['name']` and `session['email']` to the new user's values (pre-existing behaviour, out of scope), but `session['role']` is unaffected.
2. ~~Should non-Lead users receive a styled 403 page?~~ **Resolved: plain text.** Match the QE-7360 precedent — `return 'Forbidden', 403`. No styled page.
3. ~~Should `newdb.html` be wrapped in a role guard as defensive layering?~~ **Resolved: route-level only.** Route guard is the security fix; template guard for `newdb.html` is unnecessary polish given the ticket scope.
