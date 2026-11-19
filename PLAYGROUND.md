# Your ServiceNow and Neo4j playground

Run `uv sync --locked` from this project directory before using the commands below.

## Check connections without changing data

```sh
PYTHONPATH=src uv run python -m kg.check_connections
```

Both services must report `OK`. To check only ServiceNow, add `--servicenow-only`.
An HTTP 401 means the instance rejected authentication: check the instance username/password
(not the developer portal login), and whether the user needs `snc_basic_auth_api_access`.
Make sure the developer instance is awake.

The `.env` settings for Neo4j are `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, and
`NEO4J_DATABASE`. Aura uses the URI supplied by the instance, usually
`neo4j+s://<id>.databases.neo4j.io`. Local Neo4j usually uses `bolt://localhost:7687`.
Logging into the Neo4j website does not give the project database credentials.

## Prepare the outage demo once

Use a disposable ServiceNow developer instance and a Neo4j database dedicated to this project.
The mock script creates/updates CIs and relationships in ServiceNow and records changes in
`mock/ledger.json`. Its specification assumes particular demo records; a different instance's
data may need adaptation. The graph loader deletes all existing nodes in the selected Neo4j
database before rebuilding it.

```sh
mkdir -p out/pdi
PYTHONPATH=src uv run python mock/build_mock.py
PYTHONPATH=src uv run python src/kg/pdi.py
PYTHONPATH=src uv run python src/kg/load_pdi.py
```

Do not continue if any command fails. The mock step also supplies the alert file required
by this demo's loader. See README.md for Neo4j version/query-language requirements.

## Change something and see it reflected

1. In ServiceNow, open a CMDB configuration item, such as a server. Copy its `sys_id`
   (right-click the form header and use Copy sys_id), and note its current Short description.
2. Set Short description to `Ash connectivity test`, then save/update the record.
3. Download and reload, using the same dedicated Neo4j database:

   ```sh
   PYTHONPATH=src uv run python src/kg/pdi.py
   PYTHONPATH=src uv run python src/kg/load_pdi.py
   ```

4. In Neo4j Browser or Aura's query tool run:

   ```cypher
   MATCH (n:CI {sys_id: 'PASTE_THE_SYS_ID_HERE'})
   RETURN n.name, n.short_description, n.src_table, n.src_instance,
          n.extracted_at, n.load_run;
   ```

   The description should now be `Ash connectivity test`. You can also find it with
   `queries/playground.cypher`.
5. Restore the original description in ServiceNow and repeat the download/reload to undo
   the experiment in the graph.

## How Neo4j fits in

ServiceNow is the source of records and dependencies. `pdi.py` reads its APIs into
`out/pdi/`; `load_pdi.py` turns those files into Neo4j nodes and relationships.
The `.cypher` files query the graph to show topology, failure impact, and responsible teams.
This is a manual snapshot refresh: editing ServiceNow does not update Neo4j immediately,
and editing Neo4j does not write back to ServiceNow. A reload replaces graph-only edits.

After the mock and graph load succeed, run `queries/demo_topology.cypher`,
`queries/demo_outage.cypher`, and `queries/demo_who_to_call.cypher` in your Neo4j query tool.
For a topology experiment, change a CI relationship in ServiceNow, refresh, and rerun the
topology query. Record the original relationship so you can restore it.
