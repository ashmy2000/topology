// Neo4j Browser demo: the Bond Trading business application and every CI below it (38 nodes, 67 links).
// Collecting the CIs first returns each link once: 67 rows instead of 1,134 paths.
MATCH (a:BusinessApplication {name: 'Bond Trading'})
      -[:CONSUMES|DEPENDS_ON|HOSTED_ON|RUNS_ON|MEMBERS|CONNECTED_BY|CONNECTS_TO|LOCATED_IN|CONTAINS]->+(x)
WITH a, collect(DISTINCT x) AS below
UNWIND [a] + below AS n
MATCH (n)-[r:CONSUMES|DEPENDS_ON|HOSTED_ON|RUNS_ON|MEMBERS|CONNECTED_BY|CONNECTS_TO|LOCATED_IN|CONTAINS]->(m)
WHERE m IN below
RETURN n, r, m;
