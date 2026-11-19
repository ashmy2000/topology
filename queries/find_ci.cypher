// A CI by sys_id or name; a name can match several CIs (202 names repeat on the PDI).
MATCH (c:CI) WHERE c.sys_id = $key OR c.name = $key
RETURN c.sys_id AS sys_id, c.name AS name, c.sys_class_name AS class;
