// Business applications above the failure, through the services they consume.
// Down: a consumed service that is not a DR copy is down. At risk: only the DR copy is down, or a service is at risk.
// The DR copy is stale ("data current only to the failure") when something under it receives data from a down CI.
MATCH (app:BusinessApplication)-[:CONSUMES]->(s:CI)
WITH app, s,
     EXISTS { (app)-[:CONSUMES]->(:CI)-[:DR_PROVIDED_BY]->(s) } AS is_dr,
     EXISTS { MATCH (s)-[:DEPENDS_ON|HOSTED_ON|RUNS_ON]->*(:CI)-[:RECEIVES_DATA_FROM]->(source:CI)
              WHERE source.sys_id IN $down } AS stale
WITH app, collect({sys_id: s.sys_id, name: s.name, is_dr: is_dr, stale: stale}) AS consumed
WHERE any(c IN consumed WHERE c.sys_id IN $down OR c.sys_id IN $at_risk)
WITH app, consumed, [c IN consumed WHERE c.is_dr][0] AS dr
RETURN app.sys_id AS sys_id, app.name AS name, 'business application' AS kind,
       CASE WHEN any(c IN consumed WHERE NOT c.is_dr AND c.sys_id IN $down) THEN 'down'
            WHEN dr.sys_id IN $down THEN 'at risk: DR copy lost'
            ELSE 'at risk' END AS status,
       app.business_criticality_label AS criticality,
       dr.name AS dr_copy,
       CASE WHEN dr IS NULL THEN null
            WHEN dr.sys_id IN $down THEN 'down'
            WHEN dr.stale THEN 'up, data current only to the failure'
            ELSE 'up' END AS dr_status
ORDER BY name;
