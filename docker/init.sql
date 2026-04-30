-- ============================================================
-- RF Historic local dev seed data
-- Three scenarios to validate the dashboard redirect logic:
--   1. rf_full_data     - full RF results (dashboard should render normally)
--   2. roomba_sync_data - executions only, no suite/test rows (should redirect to ehistoric)
--   3. empty_project    - no executions at all (should show no-data redirect page)
-- ============================================================

-- ------------------------------------------------------------
-- Bootstrap: core registry database and user accounts database
-- ------------------------------------------------------------
CREATE DATABASE IF NOT EXISTS robothistoric;
CREATE DATABASE IF NOT EXISTS accounts;

USE accounts;

CREATE TABLE IF NOT EXISTS TB_USERS (
    id       INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    name     VARCHAR(255),
    email    VARCHAR(255),
    password VARCHAR(255)
);

-- Test login: admin@local / admin
INSERT INTO TB_USERS (name, email, password)
VALUES ('Admin', 'admin@local', '$2b$12$/3e9h/RIPYK2xIKOoIVXd.mpHrBT4AsWkv8wJYXTrQWJEu4Ah3v8u');

USE robothistoric;

CREATE TABLE IF NOT EXISTS TB_PROJECT (
    Project_Id         INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    Project_Name       VARCHAR(255),
    Project_Desc       TEXT,
    Project_Image      TEXT,
    Created_Date       DATETIME,
    Last_Updated       DATETIME,
    Total_Executions   INT,
    Recent_Pass_Perc   FLOAT,
    Overall_Pass_Perc  FLOAT
);

INSERT INTO TB_PROJECT (Project_Id, Project_Name, Project_Desc, Project_Image, Created_Date, Last_Updated, Total_Executions, Recent_Pass_Perc, Overall_Pass_Perc)
VALUES
    (0, 'rf_full_data',     'Full RF results - dashboard should render normally', '', NOW(), NOW(), 3, 75.0, 70.0),
    (0, 'roomba_sync_data', 'Roomba synced executions only - should redirect to ehistoric', '', NOW(), NOW(), 2, 0.0, 0.0),
    (0, 'empty_project',    'No executions at all - should show no-data redirect page', '', NOW(), NOW(), 0, 0.0, 0.0);

-- ------------------------------------------------------------
-- Scenario 1: rf_full_data - executions + suites + tests
-- ------------------------------------------------------------
CREATE DATABASE IF NOT EXISTS rf_full_data;
USE rf_full_data;

CREATE TABLE IF NOT EXISTS TB_EXECUTION (
    Execution_Id    INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    Execution_Date  DATETIME,
    Execution_Desc  TEXT,
    Execution_Total INT,
    Execution_Pass  INT,
    Execution_Fail  INT,
    Execution_Time  FLOAT,
    Execution_STotal INT,
    Execution_SPass  INT,
    Execution_SFail  INT,
    Execution_Skip   INT,
    Execution_SSkip  INT
);

CREATE TABLE IF NOT EXISTS TB_SUITE (
    Suite_Id      INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    Execution_Id  INT,
    Suite_Name    TEXT,
    Suite_Status  CHAR(4),
    Suite_Total   INT,
    Suite_Pass    INT,
    Suite_Fail    INT,
    Suite_Time    FLOAT,
    Suite_Skip    INT
);

CREATE TABLE IF NOT EXISTS TB_TEST (
    Test_Id          INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    Execution_Id     INT,
    Test_Name        TEXT,
    Test_Status      CHAR(4),
    Test_Time        FLOAT,
    Test_Error       TEXT,
    Test_Comment     TEXT,
    Test_Assigned_To TEXT,
    Test_ETA         TEXT,
    Test_Review_By   TEXT,
    Test_Issue_Type  TEXT,
    Test_Tag         TEXT,
    Test_Updated     TEXT
);

INSERT INTO TB_EXECUTION (Execution_Date, Execution_Desc, Execution_Total, Execution_Pass, Execution_Fail, Execution_Time, Execution_STotal, Execution_SPass, Execution_SFail, Execution_Skip, Execution_SSkip)
VALUES
    (NOW() - INTERVAL 2 DAY, 'Run 1', 4, 3, 1, 12.5, 2, 1, 1, 0, 0),
    (NOW() - INTERVAL 1 DAY, 'Run 2', 4, 4, 0, 10.2, 2, 2, 0, 0, 0),
    (NOW(),                  'Run 3', 4, 3, 1, 11.8, 2, 1, 1, 0, 0);

INSERT INTO TB_SUITE (Execution_Id, Suite_Name, Suite_Status, Suite_Total, Suite_Pass, Suite_Fail, Suite_Time, Suite_Skip)
VALUES
    (1, 'Login Suite',    'FAIL', 2, 1, 1, 6.0,  0),
    (1, 'Search Suite',   'PASS', 2, 2, 0, 6.5,  0),
    (2, 'Login Suite',    'PASS', 2, 2, 0, 5.1,  0),
    (2, 'Search Suite',   'PASS', 2, 2, 0, 5.1,  0),
    (3, 'Login Suite',    'PASS', 2, 2, 0, 5.9,  0),
    (3, 'Search Suite',   'FAIL', 2, 1, 1, 5.9,  0);

INSERT INTO TB_TEST (Execution_Id, Test_Name, Test_Status, Test_Time, Test_Error)
VALUES
    (1, 'Valid login',    'PASS', 3.1, ''),
    (1, 'Invalid login',  'FAIL', 2.9, 'Element not found'),
    (1, 'Search by name', 'PASS', 3.2, ''),
    (1, 'Search by tag',  'PASS', 3.3, ''),
    (2, 'Valid login',    'PASS', 2.5, ''),
    (2, 'Invalid login',  'PASS', 2.6, ''),
    (2, 'Search by name', 'PASS', 2.5, ''),
    (2, 'Search by tag',  'PASS', 2.5, ''),
    (3, 'Valid login',    'PASS', 2.9, ''),
    (3, 'Invalid login',  'PASS', 3.0, ''),
    (3, 'Search by name', 'FAIL', 2.9, 'Timeout waiting for results'),
    (3, 'Search by tag',  'PASS', 3.0, '');

-- ------------------------------------------------------------
-- Scenario 2: roomba_sync_data - executions only, no suite/test rows
-- ------------------------------------------------------------
CREATE DATABASE IF NOT EXISTS roomba_sync_data;
USE roomba_sync_data;

CREATE TABLE IF NOT EXISTS TB_EXECUTION (
    Execution_Id    INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    Execution_Date  DATETIME,
    Execution_Desc  TEXT,
    Execution_Total INT,
    Execution_Pass  INT,
    Execution_Fail  INT,
    Execution_Time  FLOAT,
    Execution_STotal INT,
    Execution_SPass  INT,
    Execution_SFail  INT,
    Execution_Skip   INT,
    Execution_SSkip  INT
);

CREATE TABLE IF NOT EXISTS TB_SUITE (
    Suite_Id      INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    Execution_Id  INT,
    Suite_Name    TEXT,
    Suite_Status  CHAR(4),
    Suite_Total   INT,
    Suite_Pass    INT,
    Suite_Fail    INT,
    Suite_Time    FLOAT,
    Suite_Skip    INT
);

CREATE TABLE IF NOT EXISTS TB_TEST (
    Test_Id          INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    Execution_Id     INT,
    Test_Name        TEXT,
    Test_Status      CHAR(4),
    Test_Time        FLOAT,
    Test_Error       TEXT,
    Test_Comment     TEXT,
    Test_Assigned_To TEXT,
    Test_ETA         TEXT,
    Test_Review_By   TEXT,
    Test_Issue_Type  TEXT,
    Test_Tag         TEXT,
    Test_Updated     TEXT
);

-- Only executions - no suite or test rows (simulates roomba sync)
INSERT INTO TB_EXECUTION (Execution_Date, Execution_Desc, Execution_Total, Execution_Pass, Execution_Fail, Execution_Time, Execution_STotal, Execution_SPass, Execution_SFail, Execution_Skip, Execution_SSkip)
VALUES
    (NOW() - INTERVAL 1 DAY, 'Roomba sync run 1', 0, 0, 0, 0.0, 0, 0, 0, 0, 0),
    (NOW(),                  'Roomba sync run 2', 0, 0, 0, 0.0, 0, 0, 0, 0, 0);

-- ------------------------------------------------------------
-- Scenario 3: empty_project - no data at all (tables exist but are empty)
-- ------------------------------------------------------------
CREATE DATABASE IF NOT EXISTS empty_project;
USE empty_project;

CREATE TABLE IF NOT EXISTS TB_EXECUTION (
    Execution_Id    INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    Execution_Date  DATETIME,
    Execution_Desc  TEXT,
    Execution_Total INT,
    Execution_Pass  INT,
    Execution_Fail  INT,
    Execution_Time  FLOAT,
    Execution_STotal INT,
    Execution_SPass  INT,
    Execution_SFail  INT,
    Execution_Skip   INT,
    Execution_SSkip  INT
);

CREATE TABLE IF NOT EXISTS TB_SUITE (
    Suite_Id      INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    Execution_Id  INT,
    Suite_Name    TEXT,
    Suite_Status  CHAR(4),
    Suite_Total   INT,
    Suite_Pass    INT,
    Suite_Fail    INT,
    Suite_Time    FLOAT,
    Suite_Skip    INT
);

CREATE TABLE IF NOT EXISTS TB_TEST (
    Test_Id          INT NOT NULL AUTO_INCREMENT PRIMARY KEY,
    Execution_Id     INT,
    Test_Name        TEXT,
    Test_Status      CHAR(4),
    Test_Time        FLOAT,
    Test_Error       TEXT,
    Test_Comment     TEXT,
    Test_Assigned_To TEXT,
    Test_ETA         TEXT,
    Test_Review_By   TEXT,
    Test_Issue_Type  TEXT,
    Test_Tag         TEXT,
    Test_Updated     TEXT
);
-- No rows inserted - empty tables
