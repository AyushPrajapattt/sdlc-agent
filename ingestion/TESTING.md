# Ingestion Testing

Run the unit tests from the `ingestion` directory:

```bash
python -m unittest discover -s tests/unit -v
```

Unit tests use local fixtures and test doubles, so they do not require a live Neo4j database.

## Neo4j integration tests

Configure these environment variables locally before running integration tests:

- `NEO4J_URI`
- `NEO4J_USERNAME`
- `NEO4J_PASSWORD`
- `NEO4J_DATABASE` (optional)

Run:

```bash
python -m unittest discover -s tests/integration -v
```

**Warning:** Integration tests delete `Artifact` nodes during test setup and teardown. Use a disposable test database, never a production or shared database.

Never commit credentials or `.env` files containing secrets.
