PRAGMA foreign_keys = ON;
PRAGMA user_version = 4;

CREATE TABLE documents (
    document_key INTEGER PRIMARY KEY,
    document_id TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    media_type TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    original_bytes INTEGER NOT NULL CHECK(original_bytes >= 0),
    row_count INTEGER,
    content BLOB,
    metadata TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata)),
    json_content TEXT CHECK(json_content IS NULL OR json_valid(json_content))
);

CREATE TABLE market_data (
    observation_id INTEGER PRIMARY KEY,
    source_id TEXT NOT NULL REFERENCES documents(document_id),
    source_row INTEGER NOT NULL,
    record_type TEXT NOT NULL CHECK(record_type IN ('prices','calendar','rates','rate-trace')),
    dataset_id TEXT NOT NULL,
    series_id TEXT NOT NULL,
    observation_date TEXT NOT NULL,
    rate_id TEXT,
    open TEXT, high TEXT, low TEXT, close TEXT, adj_close TEXT,
    volume INTEGER, dividends TEXT, stock_splits TEXT, capital_gains TEXT,
    adjustment_factor TEXT, adj_open TEXT, adj_high TEXT, adj_low TEXT,
    quoted_value TEXT, available_at TEXT, valid_until TEXT,
    open_at TEXT, close_at TEXT, previous_session_date TEXT, next_session_date TEXT,
    session_number INTEGER, early_close INTEGER, decision_at TEXT,
    status TEXT, reason TEXT,
    details TEXT NOT NULL CHECK(json_valid(details)),
    UNIQUE(source_id, source_row)
);
CREATE INDEX market_series ON market_data(dataset_id, record_type, series_id, observation_date);

CREATE TABLE configurations (
    configuration_key INTEGER PRIMARY KEY,
    configuration_id TEXT NOT NULL UNIQUE,
    source_id TEXT NOT NULL REFERENCES documents(document_id),
    source_row INTEGER NOT NULL,
    instrument_id TEXT NOT NULL,
    config_key TEXT NOT NULL,
    family TEXT NOT NULL CHECK(family IN ('P-SMA','MOM','MR-Z')),
    sessions INTEGER NOT NULL CHECK(sessions > 0),
    entry_threshold TEXT,
    label TEXT NOT NULL,
    broad INTEGER NOT NULL CHECK(broad IN (0,1)),
    local INTEGER NOT NULL CHECK(local IN (0,1)),
    details TEXT NOT NULL CHECK(json_valid(details)),
    UNIQUE(instrument_id, config_key),
    CHECK(broad = 1 OR local = 1)
);

CREATE TABLE executions (
    execution_key INTEGER PRIMARY KEY,
    execution_id TEXT NOT NULL UNIQUE,
    configuration_id TEXT NOT NULL REFERENCES configurations(configuration_id),
    dataset_id TEXT NOT NULL REFERENCES documents(document_id),
    source_id TEXT NOT NULL REFERENCES documents(document_id),
    source_row INTEGER NOT NULL,
    campaign_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    case_key TEXT NOT NULL,
    length_years INTEGER NOT NULL CHECK(length_years IN (1,2,3,5,7)),
    engine_version INTEGER NOT NULL,
    status TEXT NOT NULL,
    details TEXT NOT NULL CHECK(json_valid(details))
);
CREATE INDEX execution_case ON executions(campaign_id, case_key, execution_id);

CREATE TABLE daily_results (
    block_id INTEGER PRIMARY KEY,
    execution_key INTEGER NOT NULL REFERENCES executions(execution_key),
    window_id TEXT NOT NULL,
    source_key INTEGER NOT NULL REFERENCES documents(document_key),
    first_source_row INTEGER NOT NULL,
    last_source_row INTEGER NOT NULL,
    first_date TEXT NOT NULL,
    last_date TEXT NOT NULL,
    row_count INTEGER NOT NULL CHECK(row_count > 0),
    codec TEXT NOT NULL CHECK(codec = 'gzip-json-arrays-v1'),
    payload_sha256 TEXT NOT NULL,
    payload BLOB NOT NULL,
    UNIQUE(execution_key, window_id)
);
CREATE INDEX daily_source ON daily_results(source_key,first_source_row);
CREATE VIEW daily_blocks AS
SELECT e.execution_id,d.window_id,s.document_id AS source_id,d.first_source_row,
       d.last_source_row,d.first_date,d.last_date,d.row_count,d.codec,d.payload_sha256
FROM daily_results d JOIN executions e USING(execution_key)
JOIN documents s ON s.document_key=d.source_key;

CREATE TABLE evaluation_results (
    result_id INTEGER PRIMARY KEY,
    source_key INTEGER NOT NULL REFERENCES documents(document_key),
    source_row INTEGER NOT NULL,
    record_kind TEXT NOT NULL CHECK(record_kind = 'indicator'),
    field_name TEXT NOT NULL,
    execution_key INTEGER REFERENCES executions(execution_key),
    configuration_key INTEGER REFERENCES configurations(configuration_key),
    instrument_id TEXT, campaign_id TEXT, window_id TEXT, segment TEXT,
    alternative TEXT, scale TEXT, group_id TEXT,
    start_date TEXT, end_date TEXT,
    metric TEXT, exact_value TEXT, numeric_value REAL, unit TEXT, status TEXT,
    details TEXT CHECK(details IS NULL OR json_valid(details)),
    UNIQUE(source_key, source_row, field_name)
);
CREATE INDEX evaluation_scope ON evaluation_results(source_key, record_kind, source_row);
CREATE INDEX evaluation_metric ON evaluation_results(metric, instrument_id, scale, window_id);

CREATE VIEW evaluation_observations AS
SELECT r.result_id,s.document_id AS source_id,r.source_row,r.record_kind,r.field_name,
       e.execution_id,c.configuration_id,r.instrument_id,r.campaign_id,r.window_id,r.segment,
       r.alternative,r.scale,r.group_id,r.start_date,r.end_date,r.metric,r.exact_value,
       r.numeric_value,r.unit,r.status,r.details
FROM evaluation_results r JOIN documents s ON s.document_key=r.source_key
LEFT JOIN executions e USING(execution_key)
LEFT JOIN configurations c ON c.configuration_key=r.configuration_key;

CREATE VIEW cases AS
SELECT DISTINCT e.campaign_id, e.case_id, e.case_key, e.configuration_id,
       c.instrument_id, c.config_key, c.family, e.length_years
FROM executions e JOIN configurations c USING(configuration_id);

CREATE VIEW indicators AS
SELECT source_id, source_row, metric, exact_value, numeric_value, unit, status,
       execution_id, instrument_id, window_id, segment, alternative, scale, group_id
FROM evaluation_observations WHERE record_kind = 'indicator';
