CREATE TABLE IF NOT EXISTS predictions (
    id SERIAL PRIMARY KEY,
    station_id INT NOT NULL,
    target_timestamp TIMESTAMPTZ NOT NULL,
    predicted_bikes FLOAT NOT NULL,
    model_version VARCHAR(50) NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);