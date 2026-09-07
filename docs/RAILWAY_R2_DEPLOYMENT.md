# Railway + Cloudflare R2 Pilot Deployment

## Status

Railway is the selected pilot application host and Cloudflare R2 is the
selected provider-independent backup target. Both were provisioned for the
single-operator pilot in August 2026. Deployed acceptance verified runtime
health, complete R2 upload/read-back, checksum and semantic validation,
fail-loud marker handling, and clean zero-state and non-empty restore rehearsals.

Pilot Runtime SQLite Durability remains Prototype. Railway volume-specific
encryption evidence, Railway snapshot schedules, and the R2 retention controls
below remain pending; the successful deployment does not waive those gates.

This deployment runs the Stage 5 storage guardian only. It proves the durable
state, fail-loud, backup, and restore boundary. It is not a full Mission Control
briefing API and it performs no live calendar mutations.

## Why this pair

Railway can deploy directly from the canonical GitHub repository, detects the
repository Dockerfile, provides one persistent volume to the service, and
supports scheduled volume snapshots that explicitly include SQLite. Its
volume-backed service remains single-instance, matching the approved SQLite
pilot boundary.

Cloudflare R2 exposes a commodity S3-compatible API and is managed by a
different provider. Mission Control creates a consistency-safe local SQLite
backup, validates it, uploads it to R2, downloads the complete object again,
checks its SHA-256 metadata and bytes, and revalidates the SQLite schema and
workflow semantics before issuing a verified offsite receipt.

Railway's built-in volume snapshots are useful recovery points but are not the
independent copy: Railway documents that wiping a volume deletes its backups
and that those backups restore only inside the same project and environment.

Provider references:

- [Railway services and GitHub deployment](https://docs.railway.com/services)
- [Railway volume behavior and limits](https://docs.railway.com/volumes/reference)
- [Railway volume backup schedules](https://docs.railway.com/volumes/backups)
- [Railway config as code](https://docs.railway.com/config-as-code/reference)
- [Railway Trust Center](https://trust.railway.com/)
- [Cloudflare R2 pricing](https://developers.cloudflare.com/r2/pricing/)
- [Cloudflare R2 data security](https://developers.cloudflare.com/r2/reference/data-security/)
- [Cloudflare R2 S3 compatibility](https://developers.cloudflare.com/r2/api/s3/api/)
- [Cloudflare R2 bucket locks](https://developers.cloudflare.com/r2/buckets/bucket-locks/)
- [Cloudflare R2 object lifecycles](https://developers.cloudflare.com/r2/buckets/object-lifecycles/)

## Runtime topology

```text
Railway single service
  Docker image from canonical GitHub branch
  /healthz -> marked-volume + SQLite semantic verification
  internal 24-hour scheduler -> verified SQLite backup
  one Railway volume mounted at /data
    /data/state-volume       live marked state root
    /data/backup-staging     local marked staging root

Cloudflare R2
  mission-control/calendar-state/*.sqlite3
  independent verified recovery copies
```

The two local roots remain separate to prevent live-database overwrite and
unsafe restore paths, but they are on the same Railway volume and therefore do
not establish provider independence. R2 is the independent recovery boundary.
The guardian deletes its local staging copy only after the complete R2
read-back succeeds; manual CLI backups remain available until the operator
removes them.

## Account and billing checkpoint

Provisioning requires the operator to:

1. create or select a Railway account and accept its current paid usage terms;
2. connect Railway to `jdatom88/Mission-Control-Test-01`;
3. create or select a Cloudflare account and enable R2 checkout;
4. create a private R2 bucket and a least-privilege bucket token; and
5. enter the credentials only in Railway's secret-variable controls.

No credential, access key, account token, or OAuth material belongs in GitHub,
the SQLite database, deployment logs, or this document.

Current pricing must be reviewed at provisioning time. Railway is metered and
its Hobby plan includes a monthly usage credit; R2 currently includes a free
usage tier. Neither should be described as free without examining the actual
account checkout screen.

## Railway provisioning values

Create one service from the canonical repository and attach one volume at
`/data`. Create the two directories before bootstrap. Configure one replica.
Use the repository `Dockerfile` and `railway.toml`.

Required non-secret variables:

```text
MISSION_CONTROL_STATE_VOLUME_ROOT=/data/state-volume
MISSION_CONTROL_STATE_VOLUME_ID=railway-pilot-state-v1
MISSION_CONTROL_BACKUP_VOLUME_ROOT=/data/backup-staging
MISSION_CONTROL_BACKUP_VOLUME_ID=railway-local-staging-v1
MISSION_CONTROL_OFFSITE_BUCKET=<private-r2-bucket>
MISSION_CONTROL_OFFSITE_PREFIX=mission-control/calendar-state
MISSION_CONTROL_OFFSITE_ENDPOINT_URL=https://<account-id>.r2.cloudflarestorage.com
MISSION_CONTROL_OFFSITE_REGION=auto
MISSION_CONTROL_STORAGE_CHECK_SECONDS=60
MISSION_CONTROL_BACKUP_INTERVAL_SECONDS=86400
MISSION_CONTROL_BACKUP_ON_START=false
```

Required secret variables use the standard S3 client names:

```text
AWS_ACCESS_KEY_ID=<r2-bucket-token-access-key>
AWS_SECRET_ACCESS_KEY=<r2-bucket-token-secret>
```

Normal startup now requires an explicit
`MISSION_CONTROL_OFFSITE_ENDPOINT_URL`. This prevents an omitted R2 endpoint
from silently sending the S3 client toward an unintended provider endpoint.
The URL must use HTTPS and must not contain embedded credentials, a query, or a
fragment.

Do not enable multiple replicas. Railway documents that a service with a
volume cannot use replicas, and SQLite remains approved only for one runtime
writer.

## Safe R2 troubleshooting

The storage CLI reports a bounded failure category without copying provider
response messages, endpoint credentials, or request data into logs. Use the
category to choose the next check:

- credentials missing, rejected, or expired: verify the sealed Railway
  `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` values; rotate the
  bucket-scoped token only after a new token is ready;
- operation not permitted: verify that the R2 S3 token has Object Read & Write
  permission for the configured bucket;
- bucket not found: verify the exact bucket name, Cloudflare account, and any
  jurisdiction-specific endpoint;
- endpoint unreachable or TLS failure: verify the explicit HTTPS R2 endpoint
  and Railway egress before changing credentials;
- object-key conflict: choose a new `.sqlite3` backup name rather than
  overwriting the existing recovery point; and
- provider rate limit: preserve the local staging backup and retry with bounded
  delay rather than issuing concurrent backup attempts.

For a non-destructive live check, run `check` and then create one uniquely named
`backup-offsite`. The latter uploads the object, reads the complete object back,
verifies its SHA-256 metadata and bytes, and revalidates SQLite semantics before
reporting success. It does not restore over the live database.

## Bootstrap and deployment acceptance

The volume is mounted only at runtime, not during build or pre-deploy. For the
first deployment only, temporarily override the start command with the command
below. It creates the two empty roots, performs the explicit bootstrap, and
then starts the normal guardian so the configured health check can pass.

```bash
/bin/sh -c "mkdir -p /data/state-volume /data/backup-staging && python scripts/pilot_calendar_storage.py bootstrap && exec python scripts/pilot_calendar_runtime.py"
```

As soon as that deployment is healthy, remove the temporary override so
`railway.toml` supplies the normal no-bootstrap start command. Do not perform
calendar work during this short initialization window. Re-running the temporary
command against an initialized or partially initialized volume fails rather
than replacing its markers.

```bash
python scripts/pilot_calendar_storage.py bootstrap
python scripts/pilot_calendar_storage.py check
python scripts/pilot_calendar_storage.py backup-offsite \
  --name deployed-bootstrap-acceptance.sqlite3
```

Acceptance requires all of the following evidence before Issue #9 can close:

1. Railway confirms the attached volume is encrypted at rest. The public Trust
   Center lists an encryption-at-rest control, but volume-specific applicability
   must be captured rather than inferred.
2. `/healthz` returns `200` with `storage: verified` from the deployed service.
3. Removing or mismatching a marker causes startup/health failure and never
   creates an empty replacement database.
4. The first R2 object is uploaded and fully read back with matching SHA-256 and
   semantic counts.
5. Railway daily, weekly, and monthly volume snapshots are enabled as a
   same-provider recovery layer.
6. An R2 bucket lock protects the backup prefix for at least 100 days and a
   lifecycle rule expires objects only after that period. Retaining every daily
   verified object for 100 days exceeds the minimum seven-daily, four-weekly,
   and three-monthly recovery-point policy.
7. The runtime is stopped, the live database is moved to quarantine, the R2
   backup is fetched into clean staging, and restore succeeds only into the
   clean destination.
8. A separate process verifies proposal, decision, audit, receipt, and queue
   semantics after restoration.
9. No live calendar mutation occurs during durability acceptance.

Example offsite fetch before the existing clean restore command:

```bash
python scripts/pilot_calendar_storage.py fetch-offsite \
  mission-control/calendar-state/deployed-bootstrap-acceptance.sqlite3 \
  --name deployed-restore-source.sqlite3

python scripts/pilot_calendar_storage.py restore \
  /data/backup-staging/calendar-state/deployed-restore-source.sqlite3
```

Do not delete the quarantined database until the acceptance evidence has been
reviewed. Do not promote the capability merely because the container deploys.
