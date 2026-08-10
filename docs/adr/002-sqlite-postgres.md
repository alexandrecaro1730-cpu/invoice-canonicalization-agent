# ADR 002: SQLite assessment adapter with PostgreSQL production direction

## Business objective

Keep the assessment runnable on one machine while demonstrating a credible scale and isolation path.

## Technical description

**Decision:** implement the repository port with transactional SQLite and include a PostgreSQL migration using JSONB, indexes, row-level security, and pgvector-ready storage.

**Consequences:** local tests require no service dependency. Production deployment must replace the repository adapter and introduce migrations, pooling, backups, and operational monitoring.
