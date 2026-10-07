# Migration contract

1. Set `DATABASE_MIGRATION_URL` to a dedicated PostgreSQL owner account, using the
   `postgresql+psycopg://` driver. Do not use the application login.
2. Run `python -m alembic upgrade head` from `backend`.
3. A database administrator applies `sql/runtime_grants.sql` and grants the
   `salonbook_runtime` NOLOGIN group to a separately provisioned application login.
4. Every request/job must set `app.tenant_id` transaction-locally before tenant SQL.
   Missing context returns no rows and rejects inserts. Role/line/user permissions
   are additional application controls in stages 4–5, not claims made by tenant RLS.

Revisions are frozen, explicit DDL and never call `Base.metadata.create_all()` or
import live models. Autogenerate is a starting point: manually review exclusion
constraints, CHECK changes, RLS, views, triggers and grants. The tests inspect
PostgreSQL's catalogs for these objects in addition to checking metadata drift.

`0001` installs the trusted `btree_gist` extension. The migration owner needs CREATE
on the application database and schema. The extension is deliberately retained
on downgrade because it may be shared. Downgrade destroys application data and is
for disposable tests only until an operational rollback plan is approved.

`0002` sets FORCE RLS, timestamp and evidence guards. The `tenant_hostnames` view is
the only pre-tenant discovery surface: verified active hostname and tenant UUID.
It contains no secrets, user records or salon settings. The runtime role cannot
read its underlying domain table or any platform identity table.

No database connection pool, web server, API or authentication service is created
in stage 2. The SQLAlchemy metadata and migration CLI are usable independently.

Stage 3 adds `0003`: the read-only `app_schema_revision` view exposes only the
revision string to the runtime login. It cannot read or modify `alembic_version`.
When upgrading an existing installation, the migration grants SELECT if the
runtime group already exists; the bootstrap grant script also covers new installs.

The stage 3 API requires revision `0003`, a restricted runtime role, and ENABLE +
FORCE RLS on every tenant table. Startup and each service transaction verify these
prerequisites. It never runs migrations automatically. `Database.transaction()`
sets the tenant locally and completes commit/rollback before the service returns.

Stage 4 requires `0004`. It adds a session authorization fingerprint and seeds
the versioned permission catalog. Existing sessions with an empty fingerprint
must log in again. Roles are provisioned only by trusted tenant setup through
`provision_roles`; public registration can assign only the system customer role.
Deploy the API and migration together: older API versions intentionally fail
readiness against a newer schema. Downgrades remain destructive test operations.

The current build requires `0005`: mobile login, per-tenant canonical uniqueness,
phone verification state, nullable historical email and contact preference NONE.
Existing contact phone strings are not promoted to login identifiers. Use the
trusted `scripts.bind_login_mobile` tool only after matching an existing account
to its intended number. It clears phone verification and revokes existing sessions
when changing the login number. No email endpoints, SMTP or OTP provider run in
this version. Downgrade fails transactionally if phone-only accounts would violate
the old required-email schema; never synthesize addresses to force the rollback.
