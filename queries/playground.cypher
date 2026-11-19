// After changing a ServiceNow CI's Short description and refreshing the graph:
MATCH (n:CI)
WHERE n.short_description CONTAINS 'Ash connectivity test'
RETURN n.sys_id, n.name, n.short_description, n.src_table, n.src_instance,
       n.extracted_at, n.load_run;
