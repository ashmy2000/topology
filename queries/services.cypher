// Services that are down or at risk. A service group (ApplicationServiceGroup) is a folder, not a service.
MATCH (s:Service) WHERE (s.sys_id IN $down OR s.sys_id IN $at_risk) AND NOT s:ApplicationServiceGroup
RETURN s.sys_id AS sys_id, s.name AS name, 'service' AS kind,
       CASE WHEN s.sys_id IN $down THEN 'down' ELSE 'at risk' END AS status,
       s.busines_criticality AS criticality
ORDER BY name;
