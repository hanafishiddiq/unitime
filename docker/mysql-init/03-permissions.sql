USE timetable;
GRANT ALL PRIVILEGES ON timetable.* TO 'timetable'@'%';
INSERT IGNORE INTO timetable.rights (role_id, value) VALUES (1, 'ApiDataExchangeConnector');
FLUSH PRIVILEGES;
