# Vesperloom synthetic topology

[topology-synthetic.json](topology-synthetic.json) defines 13 nodes (8 CIs, 3 support groups and 2 alerts) and 19 directed relationships. SHA-256:

```text
c5eaf16b82ab0cc2c892c9bdda0ed749b2d6208b92968bd2e61bf3a43fc98485
```

Each edge is listed as start alias, type and end alias. The importer derives
32-character hexadecimal UUIDv5 IDs from the fixture namespace and each node or
edge key. Keeping the namespace and keys preserves IDs across local rebuilds.
The importer adds `src_system=synthetic`, `src_instance=vesperloom-v1`, and
synthetic source table names. Evidence paths use those names and the generated
record IDs. Every record was authored for this fixture.

| Failure to search for | Additional CIs down | At risk | Application and response |
| --- | ---: | ---: | --- |
| Vesperloom Primary Array | 6 | 0 | All three servers, the cluster, the primary service and Lantern Ledger are down. The recovery copy is up with data current only to the failure. Vesperloom Array Operations responds. |
| Vesperloom Database A | 0 | 3 | One of three cluster hosts is down. The cluster, primary service and Lantern Ledger are at risk. The recovery copy is up. Vesperloom Database Operations responds. |

Lantern Ledger Support owns the application. The primary service deliberately
has no support contact, so both responses report one ownership gap and an
uncertainty message. Both return dependency evidence and two synthetic alerts.
For the single-server failure, the array alert is adjacent to the failure and
marked off trace.

## Validate without a database

From the repository root:

```sh
PYTHONPATH=src uv run --locked python -m kg.synthetic_fixture validate
uv run --locked pytest tests/unit -q
uv run --locked ruff check .
```

## Seed and verify in a disposable local instance

The commands below use Homebrew Neo4j Community and OpenJDK 21 on macOS.
They create a separate Neo4j home in a temporary directory. Only the installed
server binaries and logging templates are reused.

```sh
(
  set -eu
  umask 077
  demo_home=$(mktemp -d /tmp/vesperloom.XXXXXXXX)
  neo_distribution="$(brew --prefix neo4j)/libexec"
  export JAVA_HOME="$(brew --prefix openjdk@21)/libexec/openjdk.jdk/Contents/Home"
  export NEO4J_HOME="$demo_home" NEO4J_CONF="$demo_home/conf"
  mkdir "$demo_home/bin" "$demo_home/conf"
  cp "$neo_distribution/bin/neo4j" "$neo_distribution/bin/neo4j-admin" "$demo_home/bin/"
  cp "$neo_distribution/conf/server-logs.xml" "$neo_distribution/conf/user-logs.xml" "$demo_home/conf/"
  ln -s "$neo_distribution/lib" "$demo_home/lib"
  cat > "$NEO4J_CONF/neo4j.conf" <<'CONFIG'
initial.dbms.default_database=topologysynthetic
server.default_listen_address=127.0.0.1
server.bolt.listen_address=127.0.0.1:17687
server.http.enabled=false
server.https.enabled=false
server.memory.heap.initial_size=256m
server.memory.heap.max_size=512m
server.memory.pagecache.size=128m
dbms.usage_report.enabled=false
CONFIG

  SYNTHETIC_NEO4J_PASSWORD=$(uv run --locked python -c 'import secrets; print(secrets.token_urlsafe(32))')
  export SYNTHETIC_NEO4J_PASSWORD
  "$demo_home/bin/neo4j-admin" dbms set-initial-password "$SYNTHETIC_NEO4J_PASSWORD"
  "$demo_home/bin/neo4j" start
  trap '"$demo_home/bin/neo4j" stop' EXIT

  PYTHONPATH=src uv run --locked python -m kg.synthetic_fixture import-local
  uv run --locked pytest tests/synthetic -q
)
```

The importer is fixed to `bolt://127.0.0.1:17687` and `topologysynthetic`.
It verifies the reported database name and checks that the graph is empty before
seeding. It writes the fixture in one transaction and refuses a second import
into the populated graph. The scenario tests use FastAPI's test client and the
existing Cypher against that database.

## Seed the designated AuraDB instance after approval

The target is `topology-practice` (instance ID `99908d7e`), Bolt database `99908d7e`, at
`neo4j+s://99908d7e.databases.neo4j.io`. The importer pins the TLS endpoint and
database name, and checks the checksum above before opening a connection. It
counts nodes and relationships before creating the synthetic ID uniqueness
constraint, then repeats the empty-graph check in the seed transaction.

Set `SYNTHETIC_AURA_URI`, `SYNTHETIC_AURA_DATABASE`, `SYNTHETIC_AURA_USER`,
and `SYNTHETIC_AURA_PASSWORD` in the untracked repository-root `.env`. These
settings are separate from the `NEO4J_*` settings used by the local API.
The second command runs read-only graph and API checks.

```sh
PYTHONPATH=src uv run --locked python -m kg.synthetic_fixture import-aura --confirm-instance 99908d7e
SYNTHETIC_TEST_AURA=1 uv run --locked pytest tests/synthetic -q
```
