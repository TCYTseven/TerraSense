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

CREATE TABLE IF NOT EXISTS mountain_satellite_images (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  mountain_slug    text NOT NULL UNIQUE REFERENCES mountains (slug) ON DELETE CASCADE,
  mountain_name    text NOT NULL,
  image_url        text NOT NULL,
  file_path        text,
  file_ext         text,
  source           text,
  download_status  text NOT NULL DEFAULT 'downloaded'
                   CHECK (download_status IN ('downloaded', 'pending', 'error')),
  bbox_west        double precision,
  bbox_south       double precision,
  bbox_east        double precision,
  bbox_north       double precision,
  image_size_px    integer,
  error            text,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now()
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
  agent_outputs jsonb NOT NULL DEFAULT '{}'::jsonb,  -- one key per agent
  -- Step 34: which hazard domain this run analyzed. Landslide is the default, so every run
  -- recorded before step 34 keeps its meaning without a backfill.
  domain        text NOT NULL DEFAULT 'landslide'
                CHECK (domain IN ('landslide', 'avalanche'))
);

CREATE TABLE IF NOT EXISTS hazards (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  mountain_id  uuid NOT NULL REFERENCES mountains (id) ON DELETE CASCADE,
  run_id       uuid REFERENCES analysis_runs (id) ON DELETE SET NULL,  -- null for a preview hazard
  -- Both domains' hazard types. app/domains.py holds the same list; tests pin them together.
  type         text NOT NULL CHECK (type IN ('landslide', 'debris_flow',
                                             'slab_avalanche', 'loose_snow_avalanche',
                                             'wet_snow_avalanche')),
  domain       text NOT NULL DEFAULT 'landslide'
               CHECK (domain IN ('landslide', 'avalanche')),
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
  end_mile     double precision,
  -- Step 19: the detour around those miles (app/bypass.py), null when none exists.
  bypass       jsonb
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
ALTER TABLE hazards ADD COLUMN IF NOT EXISTS bypass jsonb;

-- Step 34: the avalanche domain. These bring an older database up to date and do nothing on a
-- new one. The type CHECK has to be replaced rather than added to, so it is dropped by the name
-- Postgres gives an inline column constraint.
ALTER TABLE hazards ADD COLUMN IF NOT EXISTS domain text NOT NULL DEFAULT 'landslide';
ALTER TABLE hazards DROP CONSTRAINT IF EXISTS hazards_type_check;
ALTER TABLE hazards ADD CONSTRAINT hazards_type_check
  CHECK (type IN ('landslide', 'debris_flow',
                  'slab_avalanche', 'loose_snow_avalanche', 'wet_snow_avalanche'));
ALTER TABLE hazards DROP CONSTRAINT IF EXISTS hazards_domain_check;
ALTER TABLE hazards ADD CONSTRAINT hazards_domain_check
  CHECK (domain IN ('landslide', 'avalanche'));

ALTER TABLE analysis_runs ADD COLUMN IF NOT EXISTS domain text NOT NULL DEFAULT 'landslide';
ALTER TABLE analysis_runs DROP CONSTRAINT IF EXISTS analysis_runs_domain_check;
ALTER TABLE analysis_runs ADD CONSTRAINT analysis_runs_domain_check
  CHECK (domain IN ('landslide', 'avalanche'));

CREATE INDEX IF NOT EXISTS trails_mountain_idx ON trails (mountain_id);
CREATE INDEX IF NOT EXISTS analysis_runs_mountain_idx ON analysis_runs (mountain_id, started_at DESC);
CREATE INDEX IF NOT EXISTS hazards_mountain_idx ON hazards (mountain_id, created_at DESC);
CREATE INDEX IF NOT EXISTS alerts_hazard_idx ON alerts (hazard_id);
CREATE INDEX IF NOT EXISTS mountain_satellite_images_status_idx ON mountain_satellite_images (download_status);

-- Step 33: the run history log. One row per finished or failed analysis run, written by
-- app/previous_runs.py after the run stores its result. Deliberately wide and denormalized:
-- the columns are what the /history page sorts and filters on, and the jsonb columns keep the
-- whole run verbatim so nothing an agent or a model said is ever lost. Not a foreign key on
-- analysis_runs, so `python -m app.schema --reset` never takes the history with it.
CREATE TABLE IF NOT EXISTS previous_runs (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id        uuid NOT NULL UNIQUE,
  mountain_id   uuid,
  mountain_slug text NOT NULL,
  mountain_name text,
  lat           double precision,
  lon           double precision,
  elevation_m   integer,

  -- What kind of hazard the run was about. hazard_type is the pipeline's own label
  -- ('landslide' or 'debris_flow'); hazard_class is the coarse tag the history page groups by.
  -- 'avalanche' is accepted so a snow hazard has somewhere to land, but no agent emits it yet.
  hazard_class  text NOT NULL DEFAULT 'unknown'
                CHECK (hazard_class IN ('landslide', 'avalanche', 'debris_flow', 'unknown')),
  hazard_type   text,
  hazard_id     uuid,
  -- Step 34: which orchestration produced this run.
  domain        text NOT NULL DEFAULT 'landslide'
                CHECK (domain IN ('landslide', 'avalanche')),
  -- True when the run's weather was snow-dominated, which is the signal an avalanche tag
  -- would be built on once a snow hazard type exists.
  snow_driven   boolean NOT NULL DEFAULT false,

  status        text NOT NULL,
  phase         text,
  message       text,
  error         text,
  failed_agent  text,
  started_at    timestamptz NOT NULL,
  finished_at   timestamptz,
  elapsed_s     double precision,

  -- The call the run made.
  severity           text,
  confidence         double precision,
  needs_review       boolean,
  recommended_action text,
  posture            text,
  priority           text,
  headline           text,
  summary            text,

  -- The ML model's side of the run.
  model_method            text,
  model_is_stand_in       boolean,
  model_note              text,
  model_max_probability   double precision,
  model_mean_probability  double precision,
  model_share_at_high     double precision,
  model_output            jsonb NOT NULL DEFAULT '{}'::jsonb,

  -- The LLM agents' side: every agent's event and full trace, their verdicts, which
  -- provider/model answered, and the token usage summed over the run.
  agent_outputs   jsonb NOT NULL DEFAULT '{}'::jsonb,
  agent_verdicts  jsonb NOT NULL DEFAULT '{}'::jsonb,
  llm_calls       jsonb NOT NULL DEFAULT '[]'::jsonb,
  llm_usage       jsonb NOT NULL DEFAULT '{}'::jsonb,

  -- Everything else, verbatim, so a later page can show a field this table has no column for.
  advisory     jsonb,
  conditions   jsonb,
  rain         jsonb,
  run          jsonb NOT NULL,
  created_at   timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE previous_runs ADD COLUMN IF NOT EXISTS domain text NOT NULL DEFAULT 'landslide';
ALTER TABLE previous_runs DROP CONSTRAINT IF EXISTS previous_runs_domain_check;
ALTER TABLE previous_runs ADD CONSTRAINT previous_runs_domain_check
  CHECK (domain IN ('landslide', 'avalanche'));

CREATE INDEX IF NOT EXISTS previous_runs_started_idx ON previous_runs (started_at DESC);
CREATE INDEX IF NOT EXISTS previous_runs_mountain_idx ON previous_runs (mountain_slug, started_at DESC);
CREATE INDEX IF NOT EXISTS previous_runs_class_idx ON previous_runs (hazard_class, started_at DESC);
CREATE INDEX IF NOT EXISTS previous_runs_domain_idx ON previous_runs (domain, started_at DESC);
-- The past-run context tool reads this exact shape: one mountain's history in one domain.
CREATE INDEX IF NOT EXISTS previous_runs_mountain_domain_idx
  ON previous_runs (mountain_slug, domain, started_at DESC);
CREATE INDEX IF NOT EXISTS hazards_domain_idx ON hazards (mountain_id, domain, created_at DESC);
