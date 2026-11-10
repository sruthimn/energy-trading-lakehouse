-- Called by ADF after a copy succeeded. Never moves the watermark or the lsn backwards.
-- Run this file on its own: CREATE PROCEDURE must be the only statement in the batch.

CREATE OR ALTER PROCEDURE ctl.usp_update_watermark
    @source_name   NVARCHAR(64),
    @new_watermark DATETIME2(0) = NULL,
    @new_lsn       BIGINT       = NULL,
    @rows_loaded   INT,
    @run_id        NVARCHAR(64)
AS
BEGIN
    SET NOCOUNT ON;

    UPDATE ctl.watermark
    SET watermark_value = CASE WHEN @new_watermark > watermark_value
                               THEN @new_watermark ELSE watermark_value END,
        last_lsn        = CASE WHEN @new_lsn > last_lsn
                               THEN @new_lsn ELSE last_lsn END,
        rows_loaded     = @rows_loaded,
        last_run_id     = @run_id,
        last_run_time   = SYSUTCDATETIME(),
        last_status     = 'SUCCESS'
    WHERE source_name = @source_name;

    IF @@ROWCOUNT = 0
        THROW 50001, 'Unknown source_name in ctl.watermark.', 1;
END;
