-- One row per source. Safe to run again: existing rows are left alone.
-- A new source starts at 1900-01-01 and lsn 0, so its first load reads everything.

INSERT INTO ctl.watermark (source_name, load_type)
SELECT v.source_name, v.load_type
FROM (VALUES
    ('trades',              'WATERMARK'),
    ('commodities',         'FULL'),
    ('cdc_counterparties',  'CDC'),
    ('cdc_books',           'CDC'),
    ('fx_rates',            'API'),
    ('wind_solar_forecast', 'API')
) AS v (source_name, load_type)
WHERE NOT EXISTS (SELECT 1 FROM ctl.watermark w WHERE w.source_name = v.source_name);
