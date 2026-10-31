---
name: mysql-database
description: MySQL 8 guidance for schema design, constraints, migrations, indexes, locking against double booking, slow queries, backups and Windows troubleshooting. Use when working on the schema, migrations, query performance, concurrency, or database connection errors.
---

# MySQL 8

The server runs locally as the Windows service `MySQL80` on port 3306. Project database setup is in `docs/SETUP.md`. Use a dedicated app user, never root, in `.env`.

## Schema

- Use `utf8mb4` with `utf8mb4_0900_ai_ci`, and the InnoDB engine.
- Use `DECIMAL` for money.
- `CHECK` constraints are enforced in MySQL 8.0.16 and later, so use `CheckConstraint` in Django.
- Conditional unique constraints are not supported: Django's `UniqueConstraint(condition=...)` is skipped on MySQL. Enforce those rules in a locked service function.
- Exclusion constraints do not exist, so prevent overlaps with locking as shown below.
- Unique indexes on long text columns need a length limit, so keep such columns at `varchar(191)` or shorter where possible.
- The default collation is case-insensitive, so `'A@x.com'` and `'a@x.com'` collide on a unique column.

## Preventing double booking

Lock the parent row, then check for overlaps, all in one transaction:

```python
@transaction.atomic
def create_booking(resource_id, start, end, user):
    resource = Resource.objects.select_for_update().get(pk=resource_id)
    clash = Booking.objects.filter(
        resource=resource, status=Booking.Status.ACTIVE,
        start__lt=end, end__gt=start,
    ).exists()
    if clash:
        raise BookingConflict()
    return Booking.objects.create(resource=resource, start=start, end=end, user=user)
```

Lock rows in a consistent order to avoid deadlocks, and keep transactions short.

## Migrations

- Commit migration files, and do not edit ones already merged.
- Coordinate model changes across the team, since two branches adding migrations will conflict. Fix with `python manage.py makemigrations --merge`.
- During the event, if local data is disposable, dropping and reseeding is often faster than repairing a tangled migration. Never do this on a shared or deployed database without agreement.

## Performance

- Index foreign keys (automatic in InnoDB), plus columns used in filters and sorts. Use a composite index such as `(status, due_date)` for common dashboard queries.
- Run `EXPLAIN` on slow queries, and look for `type: ALL`.
- Timezone-aware date functions in Django need MySQL's time zone tables. Load them if `TruncDate` or `__date` lookups return `NULL`, or filter by datetime ranges instead.

## Backups

```powershell
mysqldump -u odooxlko -p odooxlko > backup.sql
```

Do not commit dumps that contain real data.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `Can't connect` or error 2003 | Check the service with `Get-Service MySQL80`, and start it from an administrator terminal if stopped |
| Error 1045, access denied | Check the `.env` values, and log in by hand with the same user |
| Error 1049, unknown database | Create the database (`docs/SETUP.md`) |
| Tests cannot create the database | Grant privileges on `test_odooxlko.*` to the app user |
| Error 1213, deadlock | Retry the transaction, and keep lock order consistent |
| `mysql` not recognised | Add `C:\Program Files\MySQL\MySQL Server 8.0\bin` to PATH |
