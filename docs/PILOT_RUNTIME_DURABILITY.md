# Pilot Runtime Durability Contract

## Status

Approved architecture, host-neutral controls, and deployment-ready
Railway/R2 integration are implemented. Synthetic separate-process acceptance
is complete. Actual deployed-volume and offsite-object acceptance are still
required before this capability becomes Tested or the SQLite store is relied
on operationally.

## Approved pilot boundary

The Mission Control pilot uses one cloud application runtime. That runtime is
the only process owner allowed to open the SQLite calendar-state database.
Phones, computers, and other clients communicate with the Mission Control API;
they never open or synchronize the SQLite file directly.

The live database must be stored on an encrypted persistent volume supplied by
the selected hosting platform. Backups must be stored on a separately managed
durable location so failure of the live volume cannot destroy both the database
and every recovery copy.

This is an operational decision behind the replaceable
`CalendarProposalStore` boundary. It does not make SQLite a constitutional
Mission Control dependency and does not change calendar approval semantics.

## Required runtime configuration

The pilot storage command and runtime adapter require all four local values:

```text
MISSION_CONTROL_STATE_VOLUME_ROOT
MISSION_CONTROL_STATE_VOLUME_ID
MISSION_CONTROL_BACKUP_VOLUME_ROOT
MISSION_CONTROL_BACKUP_VOLUME_ID
```

The two roots must be distinct configured locations and neither may be nested
inside the other. Path separation and volume markers prevent common
configuration mistakes, but application code cannot prove that two paths are
on physically independent storage. In the selected Railway topology they are
sibling roots on the same persistent volume: the backup root is validated local
staging, while Cloudflare R2 supplies provider independence.

Offsite commands additionally require:

```text
MISSION_CONTROL_OFFSITE_BUCKET
MISSION_CONTROL_OFFSITE_PREFIX
MISSION_CONTROL_OFFSITE_ENDPOINT_URL
MISSION_CONTROL_OFFSITE_REGION
AWS_ACCESS_KEY_ID
AWS_SECRET_ACCESS_KEY
```

The first four select a private S3-compatible object destination. The standard
AWS credential variables are Railway secrets and must never be committed or
printed.

The volume IDs are explicit operator-selected identities. One-time bootstrap
writes a role and identity marker to each mounted root. Every later open checks
those markers before touching the database. A missing or unexpected mount
therefore cannot be silently replaced by a new empty database on an ephemeral
container filesystem.

The canonical paths below the configured roots are:

```text
<state root>/calendar/calendar-state.sqlite3
<backup root>/calendar-state/
```

No OAuth credential, provider token, or other external-service secret is stored
in either location by this capability.

## Operational commands

Run commands from the repository root with the required environment values set.

### One-time bootstrap

```bash
python scripts/pilot_calendar_storage.py bootstrap
```

Bootstrap is the only operation permitted to create a new empty database. It
requires both configured roots to exist and be writable, refuses existing or
partial initialization, writes both volume markers, creates the canonical
directories, and validates the empty Mission Control schema.

### Startup and health check

```bash
python scripts/pilot_calendar_storage.py check
```

The check verifies both volume identities, expected paths, file types, write
access, SQLite write-lock availability, SQLite integrity, foreign keys, schema
compatibility, and Mission Control workflow semantics. The runtime must not
accept calendar proposals when this check fails.

### Consistency-safe backup

```bash
python scripts/pilot_calendar_storage.py backup
```

An optional simple filename may be supplied with `--name`. The operation uses
SQLite's online backup API, validates the complete backup through both SQLite
and Mission Control checks, refuses overwrite, publishes the validated copy
atomically, and returns a SHA-256 digest plus record counts.

### Verified independent backup

```bash
python scripts/pilot_calendar_storage.py backup-offsite
```

This creates and validates the local SQLite backup, uploads it through the thin
S3-compatible adapter, downloads the complete object again, compares its
SHA-256 metadata and bytes, and revalidates Mission Control semantics before it
reports success. An upload response alone is not acceptance evidence.

### Fetch verified offsite recovery source

```bash
python scripts/pilot_calendar_storage.py fetch-offsite <object-key>
```

This restricts the object to the configured prefix, downloads without
overwrite, verifies checksum and SQLite semantics, and publishes the candidate
into local backup staging. The normal clean-destination restore command remains
the only operation allowed to create the restored live database.

### Restore rehearsal or recovery

```bash
python scripts/pilot_calendar_storage.py restore <backup-path>
```

Restore accepts only a validated file inside the configured backup directory.
It refuses to overwrite any live database. For an actual recovery, stop the
Mission Control runtime and move the damaged database to a dated quarantine
location before restoring; do not destroy the original evidence. The restore
is first built and validated as a partial file, published without overwrite,
opened through the normal runtime checks, and compared semantically with the
source backup before success is reported.

## Backup and recovery policy

Minimum pilot policy:

1. Create one verified backup every 24 hours.
2. Create an additional verified backup before every schema migration or
   storage-related deployment.
3. Retain at least seven daily, four weekly, and three monthly recovery points.
4. Keep the verified offsite object storage independent from the live state
   provider and protect both with provider encryption and access controls.
5. Capture the command's timestamp, SHA-256 digest, and record counts in
   deployment logs.
6. Perform a clean restore rehearsal at least monthly and before Stable
   promotion.
7. Stop routine operation and investigate any failed backup, integrity check,
   marker check, or restore comparison.

With a 24-hour cadence, the worst-case recovery point is approximately one day.
If pilot use shows that losing a same-day briefing decision is unacceptable,
increase backup frequency or trigger a backup after each completed briefing.

## Fail-loud conditions

Mission Control stops rather than creating or reporting false state when:

- any required environment value is missing;
- the configured roots overlap;
- a root, marker, database, or backup directory is absent;
- a volume marker role or identity is unexpected;
- the expected database is missing during normal startup;
- a configured path is a symbolic link or unexpected file type;
- storage is read-only or a SQLite write lock cannot be acquired;
- the database or backup is corrupt, foreign, schema-incompatible, or
  semantically incomplete;
- a backup filename is unsafe or its destination already exists;
- a restore source is outside the configured backup directory;
- a restore destination already exists; or
- the restored snapshot differs from the validated backup.

## Acceptance evidence

The host-neutral implementation adds 14 focused tests. The repository suite now
passes 55 tests. A separate-process durability harness completed:

1. marked-volume bootstrap;
2. deferred and synthetically completed proposal persistence;
3. SQLite online backup and validation;
4. deliberate live-database loss inside a temporary acceptance directory;
5. fail-loud missing-store startup with no empty replacement;
6. clean restoration in another process; and
7. independent semantic verification of proposals, approval state, audit
   history, execution receipt, and queue state.

The harness reported:

```text
STAGE5_SEPARATE_PROCESS_DURABILITY_ACCEPTANCE=PASS
BACKUP_RESTORE_SEMANTICS=VERIFIED
MISSING_STORE_FAIL_LOUD=VERIFIED
LIVE_CALENDAR_MUTATIONS=0
```

The expanded repository suite also covers S3-compatible upload, full-object
read-back, checksum mismatch failure, safe offsite fetch, no-overwrite
publication, and guardian schedule validation. This evidence validates the
software boundary, not a particular cloud account, encrypted-volume
implementation, provider lifecycle rule, or real infrastructure failure. Those
remain required deployment acceptance work. See [Railway + Cloudflare R2 Pilot
Deployment](RAILWAY_R2_DEPLOYMENT.md).

## Migration triggers

Replace the SQLite adapter with a managed shared database when Mission Control
requires any of the following:

- multiple application instances or concurrent application writers;
- multiple users or tenant isolation;
- separate services sharing operational state directly;
- automatic database failover or tighter recovery guarantees;
- cross-region database availability; or
- a hosting platform without reliable persistent volumes.

Migration must preserve the existing proposal, approval, audit, receipt,
verification, and duplicate-safe recovery contract.
