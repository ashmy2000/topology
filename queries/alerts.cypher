// Alerts on failed CIs, and alerts on CIs one link away from a failed CI (raised, but not on the trace).
MATCH (alert:Alert)-[:ON]->(c:CI)
OPTIONAL MATCH (alert)-[:GROUPED_UNDER]->(primary:Alert)
OPTIONAL MATCH (c)-[r]-(d:CI) WHERE NOT c.sys_id IN $down AND d.sys_id IN $down
WITH alert, c, primary, collect(startNode(r).name + ' -' + type(r) + '-> ' + endNode(r).name) AS links
WHERE c.sys_id IN $down OR size(links) > 0
RETURN alert.number AS alert, alert.source AS source, alert.severity_label AS severity, c.name AS ci,
       c.sys_id IN $down AS on_trace, primary.number AS grouped_under, links
ORDER BY alert;
