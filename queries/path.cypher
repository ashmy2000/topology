// Evidence: the shortest chain from $start (a business application or service) down to a failed seed,
// through CIs that are hit ($hit: down, at risk, degraded clusters and the seeds).
// Each node and link comes with its ServiceNow record (table, sys_id): the acceptance criterion's evidence.
MATCH (start:CI {sys_id: $start})
MATCH (seed:CI) WHERE seed.sys_id IN $seeds
MATCH p = SHORTEST 1 (start)
          ((a:CI)-[:CONNECTED_BY|CONNECTS_TO|CONSUMES|DEPENDS_ON|HOSTED_ON|LOCATED_IN|MEMBERS|RUNS_ON]->(b:CI)
           WHERE b.sys_id IN $hit)+ (seed)
RETURN [n IN nodes(p) | n.name] AS names, [r IN relationships(p) | type(r)] AS types,
       [n IN nodes(p) | [n.src_table, n.sys_id]] AS node_records,
       [r IN relationships(p) | [r.src_table, r.src_sys_id]] AS link_records
ORDER BY length(p) LIMIT 1;
