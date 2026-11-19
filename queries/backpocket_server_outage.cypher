// Back pocket, Neo4j Browser (Graph view): one server of the Oracle RAC cluster fails instead of the storage array.
// Draws every chain from a service or business application down to the failed server, plus the cluster's
// other members: they still run, so the cluster survives and everything above it is at risk, not down.
// The status of each item is in backpocket_server_who_to_call.cypher.
WITH 'dbaix902nyc' AS failed_name
MATCH (failed:CI {name: failed_name})
MATCH chain = (top:CI)-[:CONSUMES|CONNECTED_BY|CONNECTS_TO|DEPENDS_ON|HOSTED_ON|LOCATED_IN|MEMBERS|RUNS_ON]->+(failed)
WHERE top:BusinessApplication OR top:Service
UNWIND nodes(chain) AS ci
OPTIONAL MATCH survivors = (ci:Cluster)-[:MEMBERS]->(other:CI)
  WHERE other <> failed AND NOT (other)-[:HOSTED_ON]->(failed)
RETURN chain, survivors;
