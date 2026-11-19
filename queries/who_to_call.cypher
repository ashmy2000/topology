// Who to call for each CI in $ids, first route that answers wins; never drops a CI.
// 1 the CI's own group fields, 2 the support group of the nearest service above it (not for services and apps),
// 3 the group of its most recent incident, 4 its managed_by person, 5 UNKNOWN.
UNWIND $ids AS id
MATCH (x:CI {sys_id: id})
CALL (x) {
  MATCH (x)-[r:SUPPORT_GROUP|ASSIGNMENT_GROUP|MANAGED_BY_GROUP]->(g:Group)
  RETURN g.name AS who, toLower(type(r)) AS route, 1 AS rank,
         CASE type(r) WHEN 'SUPPORT_GROUP' THEN 0 WHEN 'ASSIGNMENT_GROUP' THEN 1 ELSE 2 END AS tie
  UNION
  MATCH p = SHORTEST 1 (s:Service)-[:CONNECTED_BY|CONNECTS_TO|DEPENDS_ON|HOSTED_ON|MEMBERS|RUNS_ON]->+(x)
  WHERE NOT x:Service AND NOT x:BusinessApplication AND NOT s:ApplicationServiceGroup
  MATCH (s)-[:SUPPORT_GROUP]->(g:Group)
  RETURN g.name AS who, 'service ' + s.name + ', ' + toString(length(p)) + ' hops' AS route, 2 AS rank,
         length(p) AS tie
  UNION
  MATCH (i:Incident)-[:AFFECTS]->(x)
  MATCH (i)-[:ASSIGNMENT_GROUP]->(g:Group)
  // most recent incident first
  RETURN g.name AS who, 'incident ' + i.number AS route, 3 AS rank, -i.opened_at.epochSeconds AS tie
  UNION
  MATCH (x)-[:MANAGED_BY]->(person:Person)
  RETURN person.name AS who, 'managed_by' AS route, 4 AS rank, 0 AS tie
  UNION
  RETURN 'UNKNOWN' AS who, 'none' AS route, 5 AS rank, 0 AS tie
}
WITH x, who, route ORDER BY rank, tie, who
WITH x, collect({who: who, route: route})[0] AS call
OPTIONAL MATCH (x)-[:OWNED_BY]->(owner:Person)
OPTIONAL MATCH (x)-[:IT_APPLICATION_OWNER]->(it_owner:Person)
RETURN x.sys_id AS sys_id, x.name AS ci_name, call.who AS call, call.route AS route,
       owner.name AS business_owner, it_owner.name AS it_application_owner;
