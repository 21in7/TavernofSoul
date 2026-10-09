-- Run only inside a freshly created harness container, after MYSQL_USER exists.
-- Remove the entrypoint's wildcard schema grant and grant literal names instead.
REVOKE ALL PRIVILEGES, GRANT OPTION FROM 'tavern_harness'@'%';
GRANT ALL PRIVILEGES ON `tavern\_harness`.* TO 'tavern_harness'@'%';
GRANT ALL PRIVILEGES ON `test\_tavern\_harness`.* TO 'tavern_harness'@'%';
