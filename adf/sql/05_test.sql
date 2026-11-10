-- Quick check of the two procedures, using a throwaway source so real rows stay untouched.
-- Run it in the Query editor and read the result of each SELECT.

INSERT INTO ctl.watermark (source_name, load_type) VALUES ('test_source', 'WATERMARK');

-- 1. A successful run moves the watermark and the lsn forward.
EXEC ctl.usp_update_watermark @source_name = 'test_source',
     @new_watermark = '2026-03-20 17:29:55', @new_lsn = 55, @rows_loaded = 100, @run_id = 'test-1';
SELECT * FROM ctl.watermark WHERE source_name = 'test_source';

-- 2. An older value must not move it back, and NULL (an empty load) must keep the old value.
EXEC ctl.usp_update_watermark @source_name = 'test_source',
     @new_watermark = '2026-03-01', @new_lsn = NULL, @rows_loaded = 0, @run_id = 'test-2';
SELECT * FROM ctl.watermark WHERE source_name = 'test_source';

-- 3. A failure records FAILED and leaves the watermark and lsn as they were.
EXEC ctl.usp_mark_failed @source_name = 'test_source', @run_id = 'test-3';
SELECT * FROM ctl.watermark WHERE source_name = 'test_source';

-- 4. A misspelled source name must fail with an error. Expect: "Unknown source_name".
EXEC ctl.usp_mark_failed @source_name = 'tradez', @run_id = 'test-4';

-- Clean up.
DELETE FROM ctl.watermark WHERE source_name = 'test_source';
