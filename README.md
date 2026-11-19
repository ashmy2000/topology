# ServiceNow to Neo4j: outage demo

For connection checks and a change-and-refresh exercise, see [PLAYGROUND.md](PLAYGROUND.md).

Reads the CMDB (configuration management database) of a ServiceNow developer instance (PDI) into Neo4j and answers
one question: **one storage array fails. What goes down, and whom do we call?**

The PDI's demo data has no complete outage chain, so `mock/` adds one to your PDI: the business application
Bond Trading, its New York production stack down to the storage array `nyc rac nas200`, a Disaster Recovery copy in
London, and 11 mock alerts for the storage failure.

## What you need

- A Mac with [Homebrew](https://brew.sh).
- Your own ServiceNow PDI with demo data, from https://developer.servicenow.com. Tested on release Brazil
  (`glide-brazil-08-25-2026__patch1-09-21-2026`).

## 1. Install the tools

```
brew install uv
uv python install 3.14
uv sync --locked
```

`uv sync --locked` creates the project environment from `uv.lock`. Use
`uv add <package>` for runtime dependencies and `uv add --dev <package>` for
development dependencies. Both commands update `pyproject.toml` and `uv.lock`.

## 2. Set up Neo4j

If you already use Neo4j Desktop, start your local instance there and use its
connection settings in `.env`. For the Homebrew setup below, run `brew install neo4j`.

Before the first start, set a password matching `NEO4J_PASSWORD` in `.env` (the code defaults to user `neo4j`, password `password`),
and make Cypher 5 the default query language:

```
neo4j-admin dbms set-initial-password password
echo 'db.query.default_language=CYPHER_5' >> "$(brew --prefix neo4j)/libexec/conf/neo4j.conf"
brew services start neo4j
cypher-shell -u neo4j -p password "CALL dbms.components() YIELD name, versions, edition RETURN *"
```

The last command prints the Neo4j version. The Browser is at http://localhost:7474, the driver connects to
bolt://localhost:7687. The config file sits in a versioned folder: after `brew upgrade neo4j`, add the line again.

To stop and start Neo4j use `brew services stop neo4j` and `brew services start neo4j`. Avoid
`brew services restart`: it can start the new server before the old one has stopped.

## 3. Connect to your PDI

```
cp .env.example .env
```

Fill in `.env` with your instance URL, user and password. The scripts read it with python-dotenv; `.env` is
git-ignored.

If the REST API answers `401 Unauthorized` although the password works in the browser, give the user the role
`snc_basic_auth_api_access` (User Administration > Users > your user > Roles).

## 4. Add the Bond Trading outage to your PDI

```
mkdir -p out/pdi
PYTHONPATH=src uv run python mock/build_mock.py
```

`build_mock.py` applies `mock/bond_slice_spec.json` to your PDI through the REST Table API: 1 business
application, 3 new CIs (configuration items), 39 field updates, 4 deleted relationship rows and 55 new ones. Every
write is logged in `mock/ledger.json`, which keeps the old values so a change can be undone. The mock alerts
go to `out/pdi/em_alert.json` (the PDI has no event management data).

Before writing, it checks that each field it updates still holds the value the spec expects. If your PDI's demo data
differs, it stops with the field name and the live value, and nothing is updated. A second run creates nothing new:
records it made carry `MOCK demo` at the start of their short description.

## 5. Download the PDI and load the graph

```
PYTHONPATH=src uv run python src/kg/pdi.py
PYTHONPATH=src uv run python src/kg/load_pdi.py
```

`pdi.py` reads each CMDB table page by page and saves one JSON file per table in `out/pdi/`.
`load_pdi.py` empties Neo4j and rebuilds the graph from those files; it prints the nodes per kind, e.g.
`'CI': 2788`. How tables and fields become nodes and relationships: `mappings/servicenow.md`.

## 6. Run the demo

In the Neo4j Browser (http://localhost:7474, user `neo4j`, password `password`):

1. Drag `queries/estate_style.grass` onto the Browser window: it sets colours and captions.
2. Paste each query file and run it:

| File | Shows |
|---|---|
| `demo_straight_line.cypher` | One chain of 7 items, from the storage array up to Bond Trading |
| `demo_topology.cypher` | Everything Bond Trading depends on: 38 items |
| `demo_outage.cypher` | What goes down when the storage array fails, with its alerts |
| `demo_who_to_call.cypher` | Owner groups to fix and to inform (use the Table view) |
| `backpocket_server_outage.cypher` | One database server fails instead: the cluster survives |
| `backpocket_server_who_to_call.cypher` | Whom to call for that server failure |

An arrow points from the item that needs something to the item it needs, so a failure travels against the arrows.
Click a node or a relationship to see the ServiceNow table and record id it came from.

The same answer as a script: `PYTHONPATH=src uv run python src/kg/outage.py`. Set the failed CI in
`CI` at the top of the file. It runs the step queries in `queries/` and writes the result to
`out/outage/`.

## Tests

```
uv run pytest tests/unit
uv run ruff check
```

The integration tests rebuild their target graph. Run them only against a disposable Neo4j database.
They need Neo4j running, `.env` filled in and steps 4 and 5 done. Their expected counts (for
example 2,788 CIs and 271 relationship rows) are those of a Brazil PDI after the mock; a PDI with different demo data
gives different counts.

## Layout

| Path | What it holds |
|---|---|
| `src/kg/` | `pdi.py` (download), `mapping.py` (mapping config), `load_pdi.py` (graph load), `outage.py` (impact), `db.py` (Neo4j connection) |
| `mock/` | The Bond Trading changes and the script that applies them |
| `queries/` | Browser demo queries and the step queries of `outage.py` |
| `mappings/servicenow.md` | ServiceNow to graph mapping, generated by `mapping.py` |
| `tests/` | Unit tests (no services needed) and integration tests |

## Local dependency impact API

The API reads the populated Neo4j graph using the same rules as the outage CLI. Start
Topology in Neo4j Desktop and keep the existing Neo4j connection settings. Set
`IMPACT_API_KEY` to a randomly generated value of at least 32 characters in your
local `.env`. From the repository root, sync the environment and start Uvicorn:

```bash
uv sync --locked
env -u IMPACT_API_KEY PYTHONPATH=src uv run --locked uvicorn kg.api:app --host 127.0.0.1 --port 8000
```

The local launch command removes any inherited API key for that process, so the
API uses the value in `.env`. A shell-exported key otherwise takes precedence over
the file. Stop and restart Uvicorn after changing the key.
Uvicorn runs FastAPI and listens on port 8000 on your own machine. Open
<http://127.0.0.1:8000/docs> and use **Authorize** to supply the key as `X-API-Key`.
If Swagger has an older value, use **Authorize → Logout**, then authorize again
with the current value. Enter the value alone.
The OpenAPI contract is at <http://127.0.0.1:8000/openapi.json>.

| Endpoint | Purpose |
|---|---|
| `GET /health` | Checks that the API process is running. |
| `GET /ready` | Checks that the configured graph responds. |
| `GET /api/v1/cis/search?query=nyc%20rac%20nas200` | Returns matching CI records and their ServiceNow IDs. |
| `POST /api/v1/impact` | Takes a JSON body such as `{"ci_id":"<32-character sys_id>"}` and returns impact and evidence. |
| `GET /api/v1/cis/{ci_id}/ownership` | Shows the routing contact and whether the route is recorded, inferred, or missing. |

Use the search result's `sys_id` as `ci_id`. If several CIs match, use their names and
types to clarify which CI to assess. Search for `oracle` to try candidate selection.
For storage and single-server comparisons, search for `nyc rac nas200` and `dbaix902nyc`.
Compare the Bond Trading business application status and `additional_cis_down` in both
impact responses. Paths carry source table and record IDs, and gaps in path evidence
or support contacts are reported for human review.

Run the safe test suite with `uv run pytest tests/unit` and `uv run ruff check`. The
existing integration fixture rebuilds its target database. Use a disposable database
for that suite.

## Copilot Studio connector

[topology-impact.swagger.json](connectors/topology-impact.swagger.json) is the
OpenAPI 2.0 import file. It describes `searchCIs`, `assessImpact`, and
`getCIOwnership`. FastAPI's `/openapi.json` continues to serve the local OpenAPI
3.1 contract for Swagger UI. [Microsoft custom connector requirements](https://learn.microsoft.com/en-in/connectors/custom-connectors/faq)

When the Power Platform environment, data handling, and HTTPS endpoint are approved:

1. Replace `topology-api.example.com` in the import file with the approved
   API hostname. Keep the `https` scheme.
2. In the approved Power Platform environment, create a **Custom connector**
   using **Import an OpenAPI file** and select the edited copy.
3. Under **Security**, confirm **API key**, parameter name **`X-API-Key`**,
   and location **Header**. Create a connection and enter the hosted API's
   key there. The connection supplies the header. Keep the value in the
   connection and the host's secret configuration.
4. Test the three operations on the connector's **Test** tab, then add them
   as tools to **Topology Impact Investigator**. Search first, clarify
   ambiguous candidates, and send the selected candidate's exact `sys_id`
   as `ci_id`. Include evidence and ownership gaps in the summary for human
   review.

[Import a custom connector](https://learn.microsoft.com/en-in/connectors/custom-connectors/define-openapi-definition)
and [add connector tools to Copilot Studio](https://learn.microsoft.com/en-us/microsoft-copilot-studio/advanced-connectors).

## Approved Azure App Service hosting

After subscription, hosting, and data-handling approval, use an approved Linux
App Service container build with uv installed. Include `pyproject.toml`,
`uv.lock`, `.python-version`, `src/`, and `queries/`. Keep local `.env` and
`out/` out of the image. Use these commands in the build and startup stages:

```bash
uv python install 3.14
uv sync --locked --no-dev
# Container startup, after the build has synced dependencies
PYTHONPATH=src uv run --locked --no-dev --no-sync uvicorn kg.api:app --host 0.0.0.0 --port 8000
```

Configure the App Service container target port to match port `8000` and
require HTTPS at the app ingress. Use `/health` to check the process and
`/ready` to verify graph connectivity. Set `NEO4J_URI`, `NEO4J_USER`,
`NEO4J_DATABASE`, `NEO4J_PASSWORD` and `IMPACT_API_KEY` through App Service
settings, using approved secret storage such as Key Vault references for the
password and API key. Use a dedicated Neo4j account with read access to the demo
database. The hosted API needs an approved graph containing only authorized
synthetic data.

- **Managed cloud Neo4j.** Use the provider's approved endpoint over
  certificate-verified TLS, for example `neo4j+s://<approved-host>`.
  Allow the App Service outbound connection to the provider's Bolt endpoint
  through the approved network controls.
- **Private Neo4j.** Use App Service VNet integration for outbound access to
  a private Neo4j endpoint or an approved routed network. Configure private
  DNS, routing and firewall rules for Bolt, and use certificate-verified TLS.
  The connector's HTTPS route to the API is a separate inbound connection
  that the Power Platform and network owners must approve.

On the hosted app, `localhost` means the app container. Neo4j Desktop remains
the local development database.

[App Service custom containers](https://learn.microsoft.com/en-us/azure/app-service/configure-custom-container),
[VNet integration](https://learn.microsoft.com/en-us/azure/app-service/overview-vnet-integration),
and [Neo4j driver TLS](https://neo4j.com/docs/python-manual/current/connect-advanced/).
