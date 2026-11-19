// Neo4j Browser demo: what goes down when the storage array fails, with the alerts raised on it.
// Every chain from the business application down to the failed CI, plus each alert on a CI of the chain.
// Only the two owner groups the answer uses are drawn: the failed item's (fix) and Bond Trading's (inform);
// drawing every item's group turns the picture into a tangle.
WITH 'nyc rac nas200' AS failed_name
MATCH (failed:CI {name: failed_name})
MATCH chain = (:BusinessApplication)
              -[:CONSUMES|CONNECTED_BY|CONNECTS_TO|DEPENDS_ON|HOSTED_ON|LOCATED_IN|MEMBERS|RUNS_ON]->+(failed)
UNWIND nodes(chain) AS ci
OPTIONAL MATCH alerted = (:Alert)-[:ON]->(ci)
OPTIONAL MATCH owned = (ci)-[:SUPPORT_GROUP]->(:Group)
  WHERE ci = failed OR ci:BusinessApplication OR ci:Service
RETURN chain, alerted, owned;
