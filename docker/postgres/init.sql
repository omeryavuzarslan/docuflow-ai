-- Runs once, when the data volume is first created.
-- A separate database for tests, so they never touch development data.
CREATE DATABASE docuflow_test OWNER docuflow;
\connect docuflow
CREATE EXTENSION IF NOT EXISTS vector;
\connect docuflow_test
CREATE EXTENSION IF NOT EXISTS vector;
