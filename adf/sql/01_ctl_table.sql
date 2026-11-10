-- Control table: where each source stopped last time.
-- Run in the etrm database.

IF SCHEMA_ID('ctl') IS NULL EXEC('CREATE SCHEMA ctl');

IF OBJECT_ID('ctl.watermark', 'U') IS NULL
CREATE TABLE ctl.watermark (
    source_name     NVARCHAR(64)  NOT NULL PRIMARY KEY,
    load_type       VARCHAR(10)   NOT NULL CHECK (load_type IN ('FULL', 'WATERMARK', 'CDC', 'API')),
    watermark_value DATETIME2(0)  NOT NULL DEFAULT '1900-01-01', -- newest last_modified loaded
    last_lsn        BIGINT        NOT NULL DEFAULT 0,            -- CDC bookmark
    last_status     VARCHAR(10)   NOT NULL DEFAULT 'NEW' CHECK (last_status IN ('NEW', 'SUCCESS', 'FAILED')),
    rows_loaded     INT           NULL,
    last_run_time   DATETIME2(0)  NULL,
    last_run_id     NVARCHAR(64)  NULL
);
