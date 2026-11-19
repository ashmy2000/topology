// CIs recorded at a site: its cmn_location or any location below it. Physical CIs are where a site outage starts;
// logical CIs (applications, services) at the site must be reached through dependencies.
MATCH (:Location {name: $site})<-[:PART_OF]-*(:Location)<-[:LOCATED_AT]-(c:CI)
RETURN collect(DISTINCT c.sys_id) AS located,
       collect(DISTINCT CASE WHEN c:Hardware OR c:DataCenter OR c:ComputerRoom OR c:DataCenterZone OR c:Rack
                        THEN c.sys_id END) AS seeds;
