// Clusters with at least one member in $down. A cluster is down only when every member is down; otherwise degraded.
// A member counts as the server it is hosted on: the RAC cluster lists both its nodes and their servers.
MATCH (c:CI)-[:MEMBERS]->(m:CI)
WITH c, collect(m) AS members
WHERE NOT c.sys_id IN $down AND any(m IN members WHERE m.sys_id IN $down)
UNWIND members AS m
OPTIONAL MATCH (m)-[:HOSTED_ON]->(host:CI)
WITH c, members, collect(DISTINCT coalesce(host, m)) AS hosts
RETURN c.sys_id AS sys_id, c.name AS name,
       all(m IN members WHERE m.sys_id IN $down) AS all_down,
       size([h IN hosts WHERE h.sys_id IN $down]) AS hosts_down, size(hosts) AS hosts_total;
