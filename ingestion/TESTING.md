# Ingestion Testing

Run unit tests from the `ingestion` directory:

```bash
python -m unittest discover -s tests/unit -v
```

Unit tests use local fixtures and test doubles and do not require a live Neo4j database.

## Neo4j integration tests

Configure these environment variables locally:
- `NEO4J_URI`
- `NEO4J_USERNAME`
- `NEO4J_PASSWORD`
- `NEO4J_DATABASE` (optional)

Run integration tests with:

```bash
python -m unittest discover -s tests/integration -v
```

**Warning:** Integration tests delete `Artifact` nodes during setup and teardown. Use only a disposable test database, never a production or shared database.

Never commit credentials or `.env` files containing secrets.
