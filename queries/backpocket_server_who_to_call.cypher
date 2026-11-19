// who to call when one server of the Oracle RAC cluster fails.
// Fix: the failed server's support group. Inform: every service and business application above it, with its status:
// "at risk" when every chain down to the server passes a cluster that still has a running member, else "down".
// Same answer as kg/outage.py with CI = 'dbaix902nyc'.
MATCH (failed:CI {name: 'dbaix902nyc'})
OPTIONAL MATCH (failed)-[:SUPPORT_GROUP]->(fixer:Group)
RETURN 'Fix' AS call, failed.name AS item, 'down' AS status, coalesce(fixer.name, 'UNKNOWN') AS owner_group
UNION
MATCH (failed:CI {name: 'dbaix902nyc'})
MATCH chain = (top:CI)-[:CONSUMES|CONNECTED_BY|CONNECTS_TO|DEPENDS_ON|HOSTED_ON|LOCATED_IN|MEMBERS|RUNS_ON]->+(failed)
WHERE top:BusinessApplication OR top:Service
WITH top, failed, collect(chain) AS chains
WITH top, all(c IN chains WHERE any(n IN nodes(c) WHERE n:Cluster AND EXISTS {
       (n)-[:MEMBERS]->(other:CI) WHERE other <> failed AND NOT (other)-[:HOSTED_ON]->(failed) })) AS cluster_survives
OPTIONAL MATCH (top)-[:SUPPORT_GROUP]->(owner:Group)
RETURN 'Inform' AS call,
       top.name + CASE WHEN top:BusinessApplication THEN ' (business application)' ELSE ' (service)' END AS item,
       CASE WHEN cluster_survives THEN 'at risk' ELSE 'down' END AS status,
       coalesce(owner.name, 'UNKNOWN') AS owner_group;
