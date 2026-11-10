-- Called by ADF when a copy failed. Records the failure and leaves the watermark and lsn
-- as they were, so the next run starts from the same place.
-- Run this file on its own: CREATE PROCEDURE must be the only statement in the batch.

CREATE OR ALTER PROCEDURE ctl.usp_mark_failed
    @source_name NVARCHAR(64),
    @run_id      NVARCHAR(64)
AS
BEGIN
    SET NOCOUNT ON;

    UPDATE ctl.watermark
    SET last_status   = 'FAILED',
        last_run_id   = @run_id,
        last_run_time = SYSUTCDATETIME()
    WHERE source_name = @source_name;

    IF @@ROWCOUNT = 0
        THROW 50001, 'Unknown source_name in ctl.watermark.', 1;
END;
