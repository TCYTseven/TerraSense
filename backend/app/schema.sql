-- TerraSense schema. Six tables from the Data Model in context/TerraSense.md.
-- Geometry is GeoJSON stored in jsonb. No PostGIS.
--
-- Apply from backend/ with:  python -m app.schema
-- Recreate from scratch:     python -m app.schema --reset
-- Every statement is IF NOT EXISTS, so applying twice is safe.

CREATE TABLE IF NOT EXISTS mountains (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name               text NOT NULL,
  slug               text NOT NULL UNIQUE,
  lat                double precision NOT NULL CHECK (lat BETWEEN -90 AND 90),
  lon                double precision NOT NULL CHECK (lon BETWEEN -180 AND 180),
  elevation_m        integer NOT NULL,
  region             text NOT NULL,
  current_risk_level text NOT NULL DEFAULT 'low'
                     CHECK (current_risk_level IN ('low', 'moderate', 'high', 'extreme')),
  last_analyzed_at   timestamptz,
  is_live            boolean NOT NULL DEFAULT false
);

CREATE TABLE IF NOT EXISTS trails (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  mountain_id      uuid NOT NULL REFERENCES mountains (id) ON DELETE CASCADE,
  name             text NOT NULL,
  geom             jsonb NOT NULL,          -- GeoJSON LineString
  length_km        double precision,
  elevation_gain_m integer,
  UNIQUE (mountain_id, name)
);

CREATE TABLE IF NOT EXISTS trail_segments (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  trail_id    uuid NOT NULL REFERENCES trails (id) ON DELETE CASCADE,
  seq         integer NOT NULL,             -- order along the trail, from 0
  geom        jsonb NOT NULL,               -- GeoJSON LineString
  start_mile  double precision NOT NULL,
  end_mile    double precision NOT NULL,
  risk_level  text CHECK (risk_level IN ('low', 'moderate', 'high', 'extreme')),
  probability double precision CHECK (probability BETWEEN 0 AND 1),
  UNIQUE (trail_id, seq),
  CHECK (end_mile >= start_mile)
);

CREATE TABLE IF NOT EXISTS analysis_runs (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  mountain_id   uuid NOT NULL REFERENCES mountains (id) ON DELETE CASCADE,
  status        text NOT NULL DEFAULT 'running'
                CHECK (status IN ('running', 'done', 'error')),
  started_at    timestamptz NOT NULL DEFAULT now(),
  finished_at   timestamptz,
  agent_outputs jsonb NOT NULL DEFAULT '{}'::jsonb   -- one key per agent
);

CREATE TABLE IF NOT EXISTS hazards (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  mountain_id  uuid NOT NULL REFERENCES mountains (id) ON DELETE CASCADE,
  run_id       uuid REFERENCES analysis_runs (id) ON DELETE SET NULL,  -- null for a preview hazard
  type         text NOT NULL CHECK (type IN ('landslide', 'debris_flow')),
  severity     text NOT NULL CHECK (severity IN ('low', 'moderate', 'high', 'extreme')),
  probability  double precision NOT NULL CHECK (probability BETWEEN 0 AND 1),
  confidence   double precision CHECK (confidence BETWEEN 0 AND 1),
  geom         jsonb NOT NULL,               -- GeoJSON Polygon
  drivers      jsonb NOT NULL DEFAULT '[]'::jsonb,
  what         text,
  why          text,
  how_to_avoid text,
  needs_review boolean NOT NULL DEFAULT false,
  created_at   timestamptz NOT NULL DEFAULT now(),
  -- Step 18: the hero trail miles the zone covers.
  trail_id     uuid REFERENCES trails (id) ON DELETE SET NULL,
  start_mile   double precision,
  end_mile     double precision
);

CREATE TABLE IF NOT EXISTS alerts (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  hazard_id           uuid NOT NULL REFERENCES hazards (id) ON DELETE CASCADE,
  run_id              uuid REFERENCES analysis_runs (id) ON DELETE SET NULL,
  severity            text NOT NULL CHECK (severity IN ('low', 'moderate', 'high', 'extreme')),
  title               text NOT NULL,
  body                text NOT NULL,
  recommended_action  text NOT NULL CHECK (recommended_action IN ('monitor', 'close')),
  discord_message_url text,                  -- null when the Discord post failed
  created_at          timestamptz NOT NULL DEFAULT now()
);

-- Columns added after the first release. CREATE TABLE above already has them; these bring an
-- older database up to date, and do nothing on a new one.
ALTER TABLE hazards ADD COLUMN IF NOT EXISTS trail_id uuid REFERENCES trails (id) ON DELETE SET NULL;
ALTER TABLE hazards ADD COLUMN IF NOT EXISTS start_mile double precision;
ALTER TABLE hazards ADD COLUMN IF NOT EXISTS end_mile double precision;

CREATE INDEX IF NOT EXISTS trails_mountain_idx ON trails (mountain_id);
CREATE INDEX IF NOT EXISTS analysis_runs_mountain_idx ON analysis_runs (mountain_id, started_at DESC);
CREATE INDEX IF NOT EXISTS hazards_mountain_idx ON hazards (mountain_id, created_at DESC);
CREATE INDEX IF NOT EXISTS alerts_hazard_idx ON alerts (hazard_id);
