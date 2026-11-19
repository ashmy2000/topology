// Everything that fails when the CIs in $ids fail: walk against the arrows of the types that carry an outage.
// :param ids => ['<sys_id>']
MATCH (failed:CI) WHERE failed.sys_id IN $ids
MATCH (x:CI)-[:CONNECTED_BY|CONNECTS_TO|DEPENDS_ON|HOSTED_ON|LOCATED_IN|RUNS_ON]->*(failed)
RETURN collect(DISTINCT x.sys_id) AS ids;
