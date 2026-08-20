# Pilot Runtime Durability Contract

## Status

Approved architecture and implemented host-neutral controls. Synthetic
separate-process acceptance is complete. Actual deployed-volume acceptance is
still required before this capability becomes Tested or the SQLite store is
relied on operationally.

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

The pilot storage command and runtime adapter require all four values:

```text
MISSION_CONTROL_STATE_VOLUME_ROOT
MISSION_CONTROL_STATE_VOLUME_ID
MISSION_CONTROL_BACKUP_VOLUME_ROOT
MISSION_CONTROL_BACKUP_VOLUME_ID
```

The two roots must be distinct configured locations and neither may be nested
inside the other. The deployment operator must map them to independent durable
storage. Path separation and volume markers prevent common configuration
mistakes, but application code cannot prove that a hosting provider placed two
paths on physically independent storage.

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
4. Keep backup storage independent from the live state volume and protect both
   with hosting-platform encryption and access controls.
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

This evidence validates the software boundary, not a particular cloud host,
encrypted-volume implementation, backup scheduler, or real infrastructure
failure. Those remain required deployment acceptance work.

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
