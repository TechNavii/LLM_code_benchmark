## Alembic Migrations

This directory contains database migration scripts managed by Alembic. To generate a new migration:

```
alembic revision --autogenerate -m "describe change"
```

Apply migrations:

```
alembic upgrade head
```
