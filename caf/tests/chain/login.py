"""A password-free desk login, so a playbook can be driven as a real user.

    bench --site development.localhost execute caf.tests.chain.login.link \
        --kwargs "{'email': 'natalie@caf.com'}"

    -> prints a one-time URL. Open it in the browser and you ARE that user:
       their roles, their User Permissions, their session, the desk's own
       permission checks, and the client-side JS nothing else here tests.

🔴 WHY THIS EXISTS, AND WHY IT IS NOT "JUST TYPE THE PASSWORD"
--------------------------------------------------------------
T-45's climbs are driven through a browser as the actual role-holder. The obvious
route — type `natalie@…` / `abc@123` into the login form — is one I may not take:
I do not put passwords or API tokens into forms, and that covers this project's
dummy test logins and the per-role tokens in `test_fixture_credentials.md` alike.

⭐ **Frappe already ships the answer, and it is better engineering anyway.** It is
the "Login with Email Link" button on the login page:

    frappe/www/login.py:176  _generate_temporary_login_link(email, expiry)
        key = frappe.generate_hash()
        frappe.cache.set_value(f"one_time_login_key:{key}", email,
                               expires_in_sec=expiry * 60)
        return get_url(".../login_via_key?key=" + key)

    frappe/www/login.py:189  login_via_key(key)
        frappe.cache.delete_value(cache_key)        <- SINGLE USE
        frappe.local.login_manager.login_as(email)  <- a real session

So: no credential is typed, nothing lands in the playbook file, the link dies on
first use or on expiry, and every run starts from a fresh session.

⚠️ **The private helper is used deliberately, not the whitelisted one.** Public
`send_login_link()` returns silently unless the `login_with_email_link` System
Setting is on, and it emails the link rather than returning it. The helper it
calls has neither behaviour.

🔴 THE RATE LIMIT IS REAL — AND IT IS ON THE CONSUMING END
-----------------------------------------------------------
Minting is free (this module runs with no `frappe.request`, and `@rate_limit`
returns early when there is none). **Spending is not.** `login_via_key` carries
`@rate_limit(limit=rate_limit_email_link_login or 5, seconds=3600, ip_based=True)`
— so **at most ~5 successful logins per hour from one IP**, counted per method
per IP in redis.

That is enough for one pass of a playbook (one role, or a handful), and NOT
enough to re-run the same playbook repeatedly within the hour. ⭐ **Design around
it: one login per role per run, and keep the session** — do not re-login between
rungs. If a climb genuinely needs more, raise
`System Settings.rate_limit_email_link_login` on the dev site rather than working
around the limiter. `budget()` below prints what is configured.

✅ THE RECIPE, VERIFIED END TO END 2026-09-12
---------------------------------------------
    1 · bench execute caf.tests.chain.login.link --kwargs "{'email': '<user>'}"
    2 · browser: navigate to the URL it printed
    3 · browser: navigate to /api/method/frappe.auth.get_logged_user
             -> {"message":"natalie@caffood.com"}        ← a real desk session

🔴 **STEP 2 REPORTS FAILURE AND SUCCEEDS ANYWAY.** `login_via_key` answers with a
redirect, and the browser tool reports *"navigation was denied or failed"* while
the session is established perfectly well. **Do not retry it** — a retry spends a
second one-time key AND a second unit of the hourly budget, for nothing. Step 3 is
how you find out; it is the only trustworthy check.

⚠️ Step 2 also means a `browser_batch` starting with that navigate **aborts the
rest of the batch**. Put the login in its own call, then batch the climb.

🔴 DEVELOPER MODE ONLY, DELIBERATELY
-------------------------------------
This mints a desk session for any user with no password, and `caf/tests/` travels
to production with the app. It is not whitelisted, so it is unreachable over HTTP
and needs shell access — but the guard costs nothing and states the intent. It
**fails closed** on a production site; enabling it there is a conscious edit, not
an accident.
"""

import frappe
from frappe.utils import get_url


DEFAULT_EXPIRY_MINUTES = 10


def _assert_dev_site():
    """Fail closed anywhere `developer_mode` is off. See the module header."""
    if not frappe.conf.get("developer_mode"):
        frappe.throw(
            "caf.tests.chain.login mints a desk session with no password and is "
            "restricted to a developer_mode site. This site has developer_mode "
            "off, which means it is production or prod-test. If a playbook must "
            "genuinely run here, that is a decision to take deliberately — edit "
            "this guard, do not pass a flag around it."
        )


def _user(email):
    """The user must exist, be enabled, and be able to reach the DESK.

    ⚠️ A Website User gets a session and then cannot open `/app` at all, which
    fails four rungs later as a permission mystery rather than here as a typo.
    """
    row = frappe.db.get_value(
        "User", email, ["name", "enabled", "user_type", "full_name"], as_dict=True)
    if not row:
        frappe.throw(f"No User {email!r}. Check the login against "
                     f"test_fixture_credentials.md — the org tree lives there.")
    if not row.enabled:
        frappe.throw(f"User {email!r} is DISABLED, so a link would mint a session "
                     f"that cannot be used.")
    if row.user_type != "System User":
        frappe.throw(
            f"User {email!r} is a {row.user_type}, not a System User — a login "
            f"link would succeed and the desk would still refuse every page. "
            f"Playbooks need a desk user.")
    return row


def _reachable(minted, base=None):
    """Rebuild the URL around the SITE NAME, because `get_url()` is not reachable.

    🔴 MEASURED 2026-09-12, first run of this helper. `get_url()` reads
    `conf.host_name`, and on this bench that is the CONTAINER's own hostname:

        http://frappe-dev:8000/api/method/...login_via_key?key=...

    `frappe-dev` resolves inside the docker network and nowhere else, so a browser
    on the Windows host cannot open it — and the failure looks like a bad link
    rather than a bad host.

    ⚠️ It must be the **site name**, not `localhost`: Frappe resolves the site from
    the Host header, and `http://localhost:8000` returns a bare **404**.

    The key is the only part worth keeping from what Frappe minted; everything
    around it is rebuilt. `base` overrides for a site reached some other way.
    """
    key = minted.rsplit("key=", 1)[-1] if "key=" in minted else minted
    root = (base or f"http://{frappe.local.site}:"
                    f"{frappe.conf.get('webserver_port') or 8000}").rstrip("/")
    return f"{root}/api/method/frappe.www.login.login_via_key?key={key}"


def url(email, minutes=DEFAULT_EXPIRY_MINUTES, base=None):
    """The one-time login URL, as a string. For callers; `link()` is for humans."""
    from frappe.www.login import _generate_temporary_login_link

    _assert_dev_site()
    _user(email)
    return _reachable(_generate_temporary_login_link(email, int(minutes)), base)


def link(email=None, minutes=DEFAULT_EXPIRY_MINUTES, base=None):
    """Print a one-time login URL for `email`. Single use, expires in `minutes`.

        bench --site <site> execute caf.tests.chain.login.link \
            --kwargs "{'email': 'natalie@caf.com'}"

    ⚠️ Returns None on purpose — `bench execute` prints whatever is returned, and
    a URL printed twice is a URL somebody copies half of.
    """
    import traceback

    try:
        if not email:
            print("Which user? e.g. --kwargs \"{'email': 'natalie@caf.com'}\"")
            print("The org tree and every test login: test_fixture_credentials.md")
            return None

        who = _user(email)
        target = url(email, minutes, base)

        print("=" * 72)
        print("ONE-TIME DESK LOGIN  ·  no password is involved")
        print("=" * 72)
        print(f"  user     : {who.name}  ({who.full_name})")
        print(f"  roles    : {', '.join(_roles(email)) or '(none)'}")
        print(f"  expires  : {minutes} min, and dies on FIRST USE")
        print()
        print(f"  {target}")
        print()
        print(f"  {budget_line()}")
        print("=" * 72)
    except Exception:
        # quirks §18 — `bench execute` masks the real exception behind its own
        # `NameError: name 'caf' is not defined`, and print_exc() goes to stderr,
        # which does not survive `docker exec`.
        print(traceback.format_exc())
    return None


def _roles(email):
    return sorted(r.role for r in frappe.get_all(
        "Has Role", filters={"parent": email, "parenttype": "User"},
        fields=["role"]))


def budget_line():
    """One line about the consuming-end rate limit. See the module header."""
    limit = frappe.get_system_settings("rate_limit_email_link_login") or 5
    return (f"rate limit: ~{limit} successful logins per HOUR per IP "
            f"(System Settings.rate_limit_email_link_login). One login per role "
            f"per run — keep the session, do not re-login between rungs.")


def budget():
    """bench execute caf.tests.chain.login.budget — what the limiter allows."""
    print(budget_line())
    return None
