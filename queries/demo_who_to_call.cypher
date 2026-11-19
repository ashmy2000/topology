// Neo4j Browser demo: who to call when the storage array fails. Show it in the Table view.
// Fix: the owner group of the failed item. Inform: the owner group of every service and business
// application that goes down, found by following the arrows back from the failed item. UNKNOWN: no owner recorded.
// Same answer as kg/outage.py for this failure (the cluster and Disaster Recovery rules change nothing here).
MATCH (failed:CI {name: 'nyc rac nas200'})
OPTIONAL MATCH (failed)-[:SUPPORT_GROUP]->(fixer:Group)
RETURN 'Fix' AS call, failed.name AS item, coalesce(fixer.name, 'UNKNOWN') AS owner_group
UNION
MATCH (top:CI)-[:CONSUMES|CONNECTED_BY|CONNECTS_TO|DEPENDS_ON|HOSTED_ON|LOCATED_IN|MEMBERS|RUNS_ON]->+(:CI {name: 'nyc rac nas200'})
WHERE top:BusinessApplication OR top:Service
WITH DISTINCT top
OPTIONAL MATCH (top)-[:SUPPORT_GROUP]->(owner:Group)
RETURN 'Inform' AS call,
       top.name + CASE WHEN top:BusinessApplication THEN ' (business application)' ELSE ' (service)' END AS item,
       coalesce(owner.name, 'UNKNOWN') AS owner_group;
