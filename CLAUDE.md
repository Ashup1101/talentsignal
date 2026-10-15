# TalentSignal — Project Specification for Claude Code

## What this is
An end-to-end job market intelligence platform. Raw job postings are ingested
from public APIs, processed at scale with PySpark on Databricks, modeled with
dbt, orchestrated by Airflow, enriched with NLP + ML, and served through a
web app on AWS EC2: a Next.js frontend (static export) over a FastAPI API.

The end product is a resume intelligence tool: a user uploads a resume PDF and
sees how it compares with what real postings ask for — skill demand, match per
target role, predicted salary, the most valuable missing skills, and matching
postings from this week. (Direction set 2026-10-04; see Phase 6.)

Goal: a publicly accessible, interview-demonstrable portfolio project covering
the full data engineering + ML stack.

## Rebuild targets (from the original project's resume description)
This repo rebuilds an earlier version of TalentSignal whose code was lost; only
the resume description survives. Each phase must deliver what it claims. The
App bullet was deliberately changed on 2026-10-04 (resume intelligence tool
instead of a market dashboard); update the resume to match what is built.
- Scale: structured analytics across 50K+ job postings (after dedup).
- Databricks PySpark: large-scale deduplication + skill extraction via UDFs.
- dbt: star-schema mart layer over RDS PostgreSQL — dim_role, dim_location,
  fact_job_postings — alongside the trend / salary / skill-demand marts.
- NLP: spaCy + BERTopic skill extraction and latent topic clustering of
  job descriptions, run in Databricks.
- ML: XGBoost salary predictor with MLflow tracking (target MAE < $9K);
  Prophet skill-demand forecaster with a 90-day horizon.
- Airflow: daily DAG using DatabricksRunNowOperator to chain ingestion →
  PySpark → dbt run → ML retraining.
- App (changed 2026-10-14 from Streamlit at the user's request): resume
  intelligence web app — Next.js static export (React, TypeScript, Tailwind,
  shadcn/ui, Recharts) over a FastAPI API — on EC2 behind nginx,
  CI/CD via GitHub Actions. Upload a resume PDF → skills found (regex +
  keyword matching with the pipeline's skill dictionary, no LLM) with their
  demand in real postings, match % per target role, XGBoost salary
  prediction, top 3 missing skills with estimated salary impact, and this
  week's matching postings.

Numbers above are targets, not facts. Measure them on real data and report
the actual result (e.g. real held-out MAE), even if it misses the target.

Resume bullets as built (measured 2026-10-15; replace the original description):
- Built an end-to-end job-market pipeline on AWS: a nightly Airflow 3 DAG (9 tasks)
  ingests JSearch and BLS data into S3 under a hard API budget, deduplicates postings
  and extracts skills with PySpark / Delta Lake (731 unique postings across 5 roles ×
  5 metros so far), and models a dbt star schema (dim_role, dim_location,
  fact_job_postings + trend, salary and skill-demand marts; 100+ dbt tests) on RDS
  PostgreSQL.
- Added NLP + ML: spaCy rule-based years-of-experience extraction (74% of postings;
  "level unknown" cut from 43% to 14%), sentence-transformers embeddings + BERTopic
  topics, an XGBoost salary model tracked in MLflow (employer-grouped 5-fold CV MAE
  $34K, 17% better than a per-role median baseline), and a Prophet demand forecaster
  gated until 12 weekly data points exist.
- Shipped a resume intelligence web app (Next.js static export + FastAPI) on EC2
  behind nginx with Let's Encrypt HTTPS: a PDF is parsed in memory (pdfplumber + the
  pipeline's skill dictionary, no LLM) into match % per role, a salary estimate, the
  most in-demand missing skills and embedding-matched postings in ~1 s.
- Automated delivery with GitHub Actions (9 jobs, incl. dbt against a throwaway
  Postgres, Docker image builds and HTTPS tests) and pull-based CD: images go to GHCR,
  the server deploys each release itself and CI runs a public smoke test; no AWS keys
  in CI, no SSH port.
Versus the original targets: 731 postings, not 50K+ (free JSearch plan: ~200
requests/month); MAE $34K vs < $9K (≈ 280 salaried postings); PySpark runs locally
(Databricks only hosts MLflow; Phase 4b not done); the DAG uses BashOperator, not
DatabricksRunNowOperator.

---

## Tech stack (use exactly these, no substitutions without asking)
- Ingestion:        Python 3.11, boto3, requests, JSearch API (RapidAPI)
- Storage:          AWS S3 (raw / processed / curated zones), AWS RDS PostgreSQL
- Processing:       PySpark, Databricks (Delta Lake format)
- Transformation:   dbt Core (dbt-postgres adapter)
- Orchestration:    Apache Airflow 3.x, pip-installed in its own virtualenv and
                    run locally with `airflow standalone` (no Docker; Docker is
                    deferred to Phase 6). 2.x dropped: end of life 2026-04-22.
- NLP:              spaCy, sentence-transformers, BERTopic (VADER dropped by the
                    user 2026-10-07: no real use in this project)
- ML:               XGBoost, Prophet, scikit-learn, MLflow (hosted on Databricks
                    Free Edition, the successor of Community Edition)
- App:              Next.js (React, TypeScript, Tailwind CSS, shadcn/ui, Recharts,
                    Lucide) as a static export; FastAPI + uvicorn; pdfplumber.
                    Streamlit replaced 2026-10-14 (user's request).
- Hosting:          AWS EC2 t3.small, nginx, systemd, GitHub Actions CI/CD
- Python deps:      managed via pyproject.toml + pip-tools

---

## Repo structure (create this exactly)
```
talentsignal/
├── CLAUDE.md
├── README.md
├── pyproject.toml
├── .gitignore
│
├── infra/
│   ├── terraform/                # S3 buckets, RDS, EC2 (scaffold only for now)
│   ├── airflow/
│   │   ├── install.sh            # creates .venv-airflow: Airflow 3 + constraints
│   │   └── run_local.sh          # env vars + `airflow standalone` (UI :8080)
│   ├── api/
│   │   └── run_local.sh          # the FastAPI API on localhost:8000 (/api/docs)
│   ├── aws/                      # Phase 6 step 6: the EC2 server (aws login --profile ts-admin)
│   │   ├── create_server.sh      # security groups, IAM role, t3.small, Elastic IP
│   │   ├── user_data.sh          # first boot: Docker, Compose, swap
│   │   ├── put_app_params.sh     # the API's 7 settings → SSM Parameter Store
│   │   └── verify_server.sh      # checks over SSM: S3/RDS from a container, ports
│   ├── deploy/                   # Phase 6 steps 7–8: HTTPS + deploys
│   │   ├── deploy.sh             # on the server: settings, images, certificate, systemd
│   │   ├── update.sh             # on the server, every 2 min: deploy the newest release
│   │   ├── run_remote.sh         # run deploy.sh on the server over SSM (first/manual deploy)
│   │   └── smoke_test.sh         # public HTTPS checks (CI release job, or a laptop)
│   ├── docker/                   # Phase 6 step 5: the app's images
│   │   ├── api.Dockerfile        # FastAPI + CPU PyTorch; OMP_NUM_THREADS=1; model baked in
│   │   ├── web.Dockerfile        # Node builds web/out/ → nginx serves it; /version.json
│   │   ├── *.Dockerfile.dockerignore  # allowlist build contexts (never .env)
│   │   ├── nginx/                # 00-http.conf, app.locations (pages + /api, resumes off
│   │   │                         #   disk), http.conf / https.conf, 40-talentsignal-tls.sh
│   │   ├── test_tls.sh           # the web image's HTTPS + first-deploy modes (CI)
│   │   └── run_local.sh          # build + start both at http://localhost/
│   ├── docker-compose.yml        # api + web (not used for Airflow)
│   └── docker-compose.prod.yml   # server additions: 443, certificates, no builds
│
├── src/
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── fetch_jobs.py         # JSearch API → S3 raw zone
│   │   ├── fetch_bls.py          # BLS Occupational Outlook → S3 raw zone
│   │   └── s3_utils.py           # boto3 helpers (upload, check exists, list)
│   │
│   ├── processing/               # PySpark jobs (run locally or on Databricks)
│   │   ├── __init__.py
│   │   ├── spark_utils.py        # SparkSession (local Delta + S3A / Databricks), bucket URIs
│   │   ├── clean_jobs.py         # flatten JSON, deduplicate, normalize
│   │   ├── clean_bls.py          # BLS raw snapshots → occupations table
│   │   ├── extract_skills.py     # PySpark UDF for skill extraction
│   │   ├── load_postgres.py      # Delta tables → RDS raw schema (JDBC)
│   │   └── postgres.py           # PostgresConfig + replace_tables() (one-transaction writer), Spark-free
│   │
│   ├── dbt_project/              # full dbt project lives here
│   │   ├── dbt_project.yml
│   │   ├── profiles.yml.example
│   │   ├── models/
│   │   │   ├── sources.yml       # raw.* (load_postgres.py) + ml.* (nlp_pipeline.py)
│   │   │   ├── staging/
│   │   │   │   ├── stg_jobs.sql
│   │   │   │   ├── stg_skills.sql
│   │   │   │   ├── stg_bls_occupations.sql
│   │   │   │   ├── stg_job_sightings.sql  # every collection, before dedup (Phase 5.0)
│   │   │   │   ├── stg_posting_nlp.sql    # years of experience per posting (Phase 5.1a)
│   │   │   │   ├── stg_topics.sql         # BERTopic topics; -1 = unassigned (Phase 5.1b)
│   │   │   │   ├── stg_posting_topics.sql # each posting's topic (Phase 5.1b)
│   │   │   │   └── stg_skill_demand_forecast.sql # forecast or gate verdict (Phase 5.3)
│   │   │   ├── intermediate/
│   │   │   │   ├── int_jobs_enriched.sql
│   │   │   │   └── int_job_skills_joined.sql
│   │   │   └── marts/
│   │   │       ├── dim_role.sql
│   │   │       ├── dim_location.sql
│   │   │       ├── fact_job_postings.sql
│   │   │       ├── mart_job_trends.sql
│   │   │       ├── mart_salary_bands.sql
│   │   │       ├── mart_skill_demand.sql
│   │   │       ├── mart_skill_salary.sql
│   │   │       ├── mart_skill_salary_by_role.sql  # within-role (Phase 5.0)
│   │   │       └── mart_role_skill_profile.sql    # demand share + salary per role × skill (Phase 6)
│   │   ├── seeds/
│   │   │   └── role_soc_mapping.csv
│   │   ├── ci/                   # dbt CI: throwaway Postgres on every PR
│   │   │   ├── make_fixtures.py  # regenerates raw_fixtures.sql from RDS (read-only)
│   │   │   └── raw_fixtures.sql  # real 50-posting sample of raw.* + ml.*
│   │   └── tests/
│   │
│   ├── dags/                     # Airflow DAGs
│   │   ├── talentsignal_pipeline.py  # daily: ingest → Spark → load → NLP → dbt → ML
│   │   └── talentsignal_bls.py       # monthly: BLS fetch → clean
│   │
│   ├── skills/                   # shared, Spark-free skill dictionary (Phase 5.0)
│   │   ├── __init__.py
│   │   └── dictionary.py         # SKILLS, patterns, find_skills(): postings AND resumes
│   │
│   ├── ml/
│   │   ├── nlp_pipeline.py       # years of experience, boilerplate filter, writes ml.* (5.1)
│   │   ├── embeddings.py         # chunked all-MiniLM-L6-v2 embeddings (postings AND resumes)
│   │   ├── topics.py             # BERTopic settings + fit_topics()
│   │   ├── salary_model.py       # XGBoost regressor + MLflow logging
│   │   ├── features.py           # resume-derivable features; SAME build_features() for training + app
│   │   ├── artifacts.py          # S3 keys of the exports the app reads (no imports)
│   │   ├── demand_forecast.py    # Prophet time-series per role × skill (gated)
│   │   └── resume_features.py    # pdfplumber text → skills → model features
│   │
│   └── api/                      # the app's Python API (FastAPI), Phase 6
│       ├── __init__.py           # pins OMP_NUM_THREADS=1 (PyTorch + XGBoost in one process)
│       ├── main.py               # endpoints: /api/options, overview, analyze, salaries, skills, forecast, insights
│       ├── schemas.py            # Pydantic response models (→ OpenAPI → frontend types)
│       ├── data.py               # read-only data access: cached RDS queries + S3 loaders
│       ├── db_setup.py           # creates app_reader, the read-only DB user (run once)
│       ├── serving.py            # salary model: load from JSON (1 thread), predict, what-if
│       └── logic.py              # match %, missing skills, salary + level median, matching
│
├── web/                          # Next.js frontend (static export → out/), Phase 6
│   ├── openapi.json              # the API's OpenAPI (python -m src.api.export_openapi)
│   ├── src/app/                  # pages: /, /analyze/, /salaries/, /skills/, /insights/
│   ├── src/components/           # page views; ui/ = shadcn components (Base UI)
│   ├── src/lib/                  # api.ts (typed client), api-types.ts (generated), format.ts, use-api.ts
│   └── public/sample-resume.pdf  # = tests/fixtures/resume_sample.pdf (made up)
│
├── tests/
│   ├── test_ingestion.py
│   ├── test_processing.py        # local SparkSession, no S3/Delta
│   ├── test_dbt_ci.py            # dbt CI fixture generator (fake cursor)
│   ├── test_dags.py              # DAGs import cleanly; task order (own CI job)
│   ├── test_skills.py            # shared skill dictionary (no Spark)
│   ├── test_ml.py                # ML smoke tests (own CI job, CPU-only PyTorch)
│   ├── test_nlp.py               # years, boilerplate filter, ml.* rows (ml CI job)
│   ├── test_embeddings.py        # chunking + weighted average; real model (ml CI job)
│   ├── test_topics.py            # BERTopic on synthetic groups (ml CI job)
│   ├── test_features.py          # salary-model features (no ML libs needed)
│   ├── test_salary_model.py      # CV, baselines, what-if, MLflow, export (ml CI job)
│   ├── test_demand_forecast.py   # gate, Prophet forecasts, backtest (ml CI job)
│   ├── test_resume_features.py   # PDF → text → skills → features (ml CI job)
│   ├── test_api_data.py          # data.py with a stub DB pool + Stubber S3
│   ├── test_db_setup.py          # app_reader statements; password only as a parameter
│   ├── test_api_logic.py         # logic + serving on stub data; OpenMP regression
│   ├── test_api_routes.py        # every endpoint via TestClient on stub data
│   ├── api_stubs.py              # stub data + tiny XGBoost model for the API tests
│   ├── test_docker.py            # OMP pin, allowlist contexts, API imports in image, nginx privacy
│   ├── test_aws_scripts.py       # AWS scripts: no port 22, pinned Compose, only the app's settings
│   ├── test_deploy_scripts.py    # deploy scripts: full SHA only, success after health, pointer
│   ├── conftest.py               # OMP_NUM_THREADS=1 (PyTorch/XGBoost OpenMP clash)
│   └── fixtures/                 # resume_sample.pdf (made up) + make_resume_pdf.py (its generator)
│
└── .github/
    └── workflows/
        └── ci.yml                # dbt test on PR, redeploy app on merge to main
```

---

## Phase plan — work one phase at a time, do not jump ahead

### Phase 1 — Ingestion (start here)
Files to build:
- src/ingestion/s3_utils.py
  - upload_json(bucket, key, data: dict) → None
  - key_exists(bucket, key) → bool
  - list_keys(bucket, prefix) → list[str]
  - All errors raised with descriptive messages; no silent failures

- src/ingestion/fetch_jobs.py
  - fetch_jobs(role: str, location: str, num_pages: int = 3) → list[dict]
    Calls JSearch API (/search-v2 endpoint; /search was retired), follows the
    response cursor (~10 jobs per page, 1 API request each), returns raw results
  - save_to_s3(jobs: list[dict], role: str, location: str) → str
    Lands as s3://{RAW_BUCKET}/jobs/raw/{role}/{location}/{date}.json
    Key is idempotent — same role+location+date never overwrites
  - __main__ block: runs a sample pull for 5 roles × 5 cities

- src/ingestion/fetch_bls.py
  - fetch_bls_outlook() → list[dict]
    Reads BLS OEWS national data (oesm{YY}nat.zip → xlsx, no API key needed;
    BLS rejects requests without a contact email in the User-Agent)
    Returns list of {occupation_code, title, total_employment, median_wage}
  - save_to_s3(data) → str (same pattern as above, prefix bls/raw/)

- pyproject.toml — define all deps for Phase 1 only

Deliverable: running `python -m src.ingestion.fetch_jobs` populates S3 with
real data. Must work end-to-end before Phase 2 starts.

### Phase 2 — PySpark processing (Databricks)
Built local-first: the same code runs on a laptop (PySpark 4.1 + Delta 4.3 +
hadoop-aws, Java 17) and on Databricks Runtime 18 LTS (Spark 4.1). Which
Databricks option to use (AWS workspace vs Free Edition, which likely can't
read our S3) is still open — decide before Phase 4.

Output: Delta tables in s3://{S3_PROCESSED_BUCKET}/delta/, each fully
rebuilt from the raw zone on every run (overwrite, idempotent; switch to
incremental MERGE only if raw volume makes full rebuilds slow).

- src/processing/clean_jobs.py → delta/jobs_clean (one row per unique posting)
  - Explicit raw schema (no inference); flatten envelopes → one row per posting
  - Normalize: title/employer text, state name → 2-letter code; salaries
    annualized (HOUR×2080, DAY×260, WEEK×52, MONTH×12); outside $20K–$1M,
    unknown period or min > max → nulled with salary_flag
  - Never fill missing city/state from the search location (that's a guess)
  - Dedup pass 1: same job_id → latest fetch. Pass 2: same normalized
    title + employer + city → keep salary present > longer description >
    latest fetch > job_id
  - Also writes delta/job_sightings (Phase 5.0): one row per posting per
    collection, BEFORE dedup. JSearch issues a new job_id on every collection
    (0 repeats in 728 sightings), so pass 2 does the real cross-collection
    merging and keeps the latest copy — jobs_clean alone would move re-seen
    postings into later weeks.
- src/processing/extract_skills.py → delta/job_skills (job_id, skill, category)
  - Curated dictionary (~110 skills, 8 categories) with aliases; ambiguous
    names (R, Go, Excel, Snowflake, ...) get case-sensitive/custom patterns
  - pandas UDF built in a factory so workers receive it by value
  - Searches title + description (/search-v2 returns no job_highlights)
- src/processing/clean_bls.py → delta/bls_occupations (latest snapshot per code)

Deliverable (met 2026-10-03, local): 702 raw → 688 clean postings; 5,202
skill mentions, 655 of 688 postings with ≥1 skill; 830 BLS occupations.

### Phase 3 — dbt modeling
Spec approved 2026-10-04. dbt-core 1.12 + dbt-postgres 1.11.

Database: AWS RDS PostgreSQL, created by the user in the console (not
Terraform — keeps talentsignal-dev limited to S3). us-east-2, db.t4g.micro,
20 GB gp3, Single-AZ, current major version (no Extended Support fees),
public access restricted to the developer's IP, SSL required. List price
≈ $17.63/month ($11.68 instance + $2.30 storage + $3.65 public IPv4).

- Load — src/processing/load_postgres.py (Spark + JDBC): read
  delta/jobs_clean, delta/job_skills, delta/bls_occupations and overwrite
  raw.jobs_clean / raw.job_skills / raw.bls_occupations, adding _loaded_at.
  Overwrite matches Phase 2's full-rebuild approach (append would duplicate
  rows on every rerun).
- profiles.yml reads the connection from env vars via env_var(); only
  profiles.yml.example is committed.
- Materializations: staging + intermediate = views; marts = tables.
- sources.yml: the 3 raw tables; freshness warns if _loaded_at > 2 days old.
- Seed role_soc_mapping.csv: the 5 search roles → BLS SOC codes, sourced
  from O*NET alternate titles with a source column. Show the mapping to the
  user before using it.
- Staging (1:1 with sources; rename/cast only): stg_jobs, stg_skills,
  stg_bls_occupations.
- Intermediate: int_jobs_enriched (rule-based seniority from title:
  intern / junior / mid / senior / staff+ / manager; skill_count),
  int_job_skills_joined (skills + role, location, posted week).
- Star schema (keys = md5 of natural keys, stable across rebuilds):
  - dim_role — one row per search role; SOC code, BLS median wage, employment
  - dim_location — one row per city + state, plus an 'Unknown' member
  - fact_job_postings — one row per posting; role/location keys,
    posted_date, seniority, is_remote, salary min/mid/max, has_salary,
    skill_count
- Marts:
  - mart_job_trends — week × role × state: postings, % remote, % with salary
  - mart_salary_bands — per role: p25 / median / p75 salary vs BLS median;
    groups with < 5 salaries marked as too few to report
  - mart_skill_demand — week × role × skill: postings mentioning it + share
    of the role's postings (feeds Prophet in Phase 5)
  - mart_skill_salary — per skill: median salary of postings that mention
    it vs. those that don't, with n on each side (feeds the app's
    missing-skill salary impact; an association, not a causal effect)
- Tests: unique / not_null keys, relationships fact → dims, accepted_values
  (skill category, salary_flag), singular tests (salary min ≤ max, shares
  in [0, 1]).
- CI: dbt build on PRs against a throwaway Postgres service container with
  small test-only fixtures — no RDS credentials in GitHub.

Status: COMPLETE (2026-10-06).
- Loader: raw.jobs_clean 688, raw.job_skills 5,202, raw.bls_occupations 830
  rows, counts verified after load.
- `dbt build` on RDS: PASS=57 (1 seed, 12 models, 44 tests) in ~7 s;
  `dbt source freshness` PASS.
- dbt CI job merged (PR #1 in the original repo, recreated 2026-10-07):
  Postgres 18 service + real 50-posting fixture
  (src/dbt_project/ci/), PASS=57 on GitHub.

Findings to carry forward:
- mart_skill_salary differences mostly reflect role mix (Excel −$65K,
  React +$45K): the app must compare within the same role before showing
  any "salary impact".
- 43% of titles state no seniority (seniority_from_title = false); the
  Phase 5 salary model should use that flag.
- Posted salary medians run 16–71% above BLS medians (expensive metros,
  senior-leaning postings, ML engineer benchmarked to data scientists).
- Only 5 weeks of posting history (2026-08-31 → 2026-09-28); Prophet needs
  far more weeks and zero-filled weekly series.

Open items:
- load_postgres: jobs_clean took ~4 min for ~4 MB on the first manual load
  (2026-10-05). NOT REPRODUCED: both Airflow runs took ~22 s (see Phase 4
  status); watch load_postgres duration in Airflow's run history.
- Console check: RDS storage type/size, Multi-AZ, Secrets Manager.
- Remove the two CloudShell IPs from the RDS security group.
- Upgrade sslmode require → verify-full (RDS CA bundle).
- Rebuilding one view alone drops dependent views (DROP … CASCADE): rebuild
  with `model+`, or run a full `dbt build`.

### Phase 4 — Airflow orchestration
Spec approved 2026-10-06 (JSearch monthly budget 180 confirmed).

Decisions (2026-10-06):
- D1 Airflow 3.x (2.x end of life 2026-04-22).
- D2 Hybrid: Spark steps run locally inside Airflow now; each stays its own
  task so it can later become a DatabricksRunNowOperator (Phase 4b).
- D3 JSearch free tier with daily rotation + hard monthly budget guard.
- D4 (revised 2026-10-06) pip-install Airflow directly on the Mac — no
  Docker/Colima for Phase 4. Docker is saved for Phase 6, where it earns
  its place.
- D5 Airflow runs on the laptop for Phase 4 (runs only while the Mac is on).

Local runtime ($0, no Docker):
- .venv-airflow/ (git-ignored): a SECOND virtualenv, Python 3.11, with
  apache-airflow 3.3.x + the standard and databricks providers, installed
  with pip and Airflow's official constraints file
  (constraints-<version>/constraints-3.11.txt). Kept apart from .venv
  because Airflow pins conflict with ours (e.g. pandas, boto3, psycopg2).
- infra/airflow/install.sh — creates .venv-airflow and installs the pinned
  version with its constraints. infra/airflow/run_local.sh — exports
  AIRFLOW_HOME, the dags folder, JAVA_HOME and
  OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES (macOS fork-safety crash; verify
  whether needed), then runs `airflow standalone` (api-server with UI at
  http://localhost:8080, scheduler, dag-processor, triggerer).
- AIRFLOW_HOME = .airflow/ in the repo (git-ignored): config, logs and the
  SQLite metadata DB. SQLite + LocalExecutor is Airflow 3's supported
  local-dev setup. It does run independent tasks in parallel: in the first
  9-task run (2026-10-13) train_salary_model and forecast_demand started
  0.2 s apart and overlapped.
  load_examples off; dags_folder = src/dags.
- Tasks run the pipeline with the project's own .venv
  (`.venv/bin/python -m …`, dbt via `.venv/bin/dotenv -f .env run -- dbt …`),
  so Airflow's environment never imports pipeline code.

DAGs (src/dags/), all tasks BashOperator calling the existing CLIs in the
pipeline venv — the same commands that run by hand:
- talentsignal_pipeline — daily 22:00 UTC (10 pm; 6 pm US Eastern),
  cron "0 22 * * *", catchup=False,
  max_active_runs=1, retries=1 (fetch_jobs: 2, 10 min apart):
  fetch_jobs → clean_jobs → extract_skills → load_postgres →
  dbt_source_freshness → dbt_build   (Phase 5.5 adds the NLP + ML tasks)
- talentsignal_bls — monthly: fetch_bls → clean_bls (BLS publishes yearly;
  the daily load_postgres picks up the latest delta/bls_occupations).

Ingestion changes (src/ingestion/fetch_jobs.py):
- CLI `--run-date {{ ds }}`. Logical dates older than yesterday are
  backfills: skip fetching (JSearch only returns current postings) and exit 0
  so downstream steps rebuild from existing raw files. Today or yesterday
  still fetches (1-day grace for late runs, e.g. the Mac asleep at 22:00).
  Raw files are always dated by the actual UTC fetch date, never the
  logical date, so nothing is mislabeled. `--dry-run` logs the plan with no
  API calls or writes.
- plan_run(): least-recently-fetched rotation over the 25 role × city pairs
  (never-fetched first, ties in fixed order), 3 pages per pair. Today's
  allowance = (budget left before today) ÷ (days left in the month) − what
  today already spent, so a same-day rerun spends nothing extra.
- Hard budget guard, two layers:
  1. Calendar-month budget JSEARCH_MONTHLY_BUDGET (default 180 of the free
     200): used = 3 × raw files dated this month, from the S3 listing alone
     (an upper bound; no downloads, so it scales to paid tiers). Each new
     envelope also records `api_requests` as an audit trail.
  2. RequestLog: before every request, refuse if RapidAPI's
     X-RateLimit-Requests-Remaining last reported ≤ JSEARCH_RESERVE_REQUESTS
     (default 20) → JSearchBudgetExhausted, run stops with exit 0.
  Upgrading to the Pro plan later = changing these env values, not code.
- Verified 2026-10-07 (dry run on real S3): 75 used in October, 25 days
  left → 4 requests/day → 1 pair/day on the free plan (2/day from November).

Tests / CI:
- Unit tests for rotation, budget math and the backfill skip.
- tests/test_dags.py: every DAG imports cleanly; task order matches the
  spec. New CI job installs Airflow with its official constraints file in
  its own environment (separate from the pytest job's dependencies).

Deliverable: `infra/airflow/install.sh` once, then `infra/airflow/run_local.sh`
→ Airflow UI on localhost:8080; a triggered talentsignal_pipeline run goes
green end to end
(new raw files for the day's rotated pairs, marts rebuilt in RDS); both
CI jobs + the DAG test job green.

Status: COMPLETE (2026-10-07).
- First runs (2026-10-07), both green on the first try:
  1. Unpausing talentsignal_pipeline immediately started a SCHEDULED run for
     the most recent missed slot (logical date 2026-10-06 22:00). catchup=False
     still runs the latest missed slot, so "unpause" = "run now". The 1-day
     grace let it fetch: 1 pair (data engineer / New York, NY), 3 requests,
     26 postings, file dated 2026-10-07; RapidAPI reported 118 remaining.
     118.5 s end to end.
  2. The MANUAL run queued behind it (max_active_runs=1), found today's
     allowance spent (75 + 3 used → 0 pairs) and fetched nothing, then rebuilt
     everything in 90.6 s. Total JSearch spend: 3 requests, no double spend.
- Results: raw.jobs_clean 688 → 704 (+16 new unique postings), raw.job_skills
  5,202 → 5,374; dbt build PASS=57; source freshness PASS.
- Task times, s (scheduled | manual): fetch_jobs 23.7 | 1.5, clean_jobs
  28.5 | 23.9, extract_skills 28.7 | 28.0, load_postgres 21.8 | 22.2,
  dbt_source_freshness 5.4 | 4.1, dbt_build 7.9 | 8.0.
- load_postgres speed finding: ~22 s per run; raw.jobs_clean (704 rows)
  written ~15 s after task start including Spark startup, job_skills ~3 s,
  bls_occupations ~2 s. The ~4 min first manual load (2026-10-05) did not
  recur with unchanged code; cause not isolated (likely a one-off of that
  session, e.g. network or first connection setup). Airflow now records every
  task's duration, so a regression would show in the run history.
- DAG left PAUSED here; switched ON 2026-10-13 (Phase 6 step 0). Nightly
  22:00 UTC runs need: infra/airflow/run_local.sh running + the Mac awake.
- Still open: a stop_local.sh for background runs (pkill on `airflow
  standalone` orphans its components; Ctrl+C in a terminal is fine);
  OBJC_DISABLE_INITIALIZE_FORK_SAFETY kept set (runs succeeded with it,
  not tested without).

Phase 4b (later, separate cost approval): Databricks workspace + jobs;
swap clean_jobs / extract_skills / load_postgres to
DatabricksRunNowOperator (+ triggerer if run deferrable).

### Phase 5 — NLP + ML models
Spec approved 2026-10-07. Built around the Phase 3 findings and this data
reality (RDS, 2026-10-07): 270 salaried postings (46–63 per role; junior 16,
manager 10; $68K–$450K); 43% of titles state no level, but 66% of those state
years of experience; posting-week history is one Oct 3 snapshot skewed toward
recent weeks, 27% undated; the role-first rotation samples each role only once
per ~25 days; 45 skills appear in ≥ 10 salaried postings.

Decisions (2026-10-07):
- D1 MLflow hosted on Databricks Free Edition (free; tracking URI
  "databricks" + personal access token in .env). Sign-up happens at the
  MLflow step, not before.
- D2 VADER dropped from the stack.
- D3 Demand = collection-week shares (not posting-week counts).
- D4 Rotation interleaved so every role is sampled every week.
- D5 The app's user picks their target seniority from a dropdown (not
  inferred from the resume).

5.0 Prerequisites (small changes to earlier phases):
- Rotation: ALL_PAIRS ordered city-first (all 5 roles for a city, then the
  next city), so least-recently-fetched ties cycle through roles.
- src/skills/dictionary.py: SKILLS, CASE_SENSITIVE, CUSTOM_PATTERNS,
  skill_patterns(), find_skills(text) — Spark-free, imported by
  extract_skills.py (postings) and resume_features.py (resumes): one set of
  patterns, identical results; a parity test guards the Spark UDF.
- dbt: int_jobs_enriched gains seniority_effective + seniority_source
  (title → years → else 'unknown'; years thresholds revised in 5.1a, see
  there; the approved seniority column stays); new
  mart_skill_salary_by_role (median with vs without each skill WITHIN a role,
  n per side, ≥ 5 per side); mart_skill_demand switches to collection week +
  shares, built from raw.job_sightings (Option B, approved 2026-10-09): per
  collection week × role, distinct postings by dedup_key; skills via the kept
  copy's dedup_key; zero-filled only in weeks the role was sampled (unsampled
  weeks = gaps, not zeros), so past weeks never change.

5.1 NLP (src/ml/nlp_pipeline.py) → RDS schema `ml`, rebuilt each run:
- spaCy rule-based Matcher: years of experience ("5+ years", "3–5 yrs",
  "four years") → ml.posting_nlp (years_min, years_max), a dbt source.
  Also a review list of frequent phrases missing from the dictionary —
  never added automatically.
- sentence-transformers (all-MiniLM-L6-v2): title + description
  embeddings, stored in the S3 curated bucket (for BERTopic and Phase 6
  resume ↔ posting matching).
- BERTopic: topics → ml.posting_topics / ml.topics for Job Insights. Not a
  salary feature (a resume has no topic → training/serving skew).

5.1a Years of experience — built 2026-10-09:
- spacy.blank("en") + Matcher (LIKE_NUM, greedy LONGEST); keeps a match only
  if it reads like a requirement (+, range, "at least/minimum/over", or an
  "experience" word within 8 tokens); drops "… ago", "… old", > 30 years.
- One posting → the mention with the LARGEST minimum ("5+ years overall,
  2+ with Spark" → 5). Known limitation: postings listing education-tiered
  alternatives ("diploma + 5 yrs or bachelor's + 3") are overstated —
  39 of 521 postings with years (7%). Kept as is (decided 2026-10-09).
- python -m src.ml.nlp_pipeline: reads raw.jobs_clean (psycopg2, no Spark),
  writes ml.posting_nlp (job_id, years_min, years_max, years_mentions,
  years_evidence, _loaded_at) in ONE transaction (create if missing →
  truncate → insert → count check); truncate, not drop, keeps dbt views.
  PostgresConfig moved to src/processing/postgres.py (Spark-free).
- Result (RDS, 704 postings, ~4.5 s): 521 (74%) state years; untitled
  postings 206 of 302 (68%).
- Thresholds (decided 2026-10-09, dbt vars seniority_min_years_*):
  junior < 2, mid 2–3, senior 4–6, staff_plus 7+. Agreement with titled
  postings' title level: 62% (the original 0–1 / 2–4 / 5–7 / 8+: 57%).
- dbt: source ml.posting_nlp (freshness warn > 2 days) → stg_posting_nlp
  (experience_years_min/max, …) → int_jobs_enriched / fact_job_postings
  gain seniority_effective, seniority_source (title / years / none),
  experience_years_min/max. Tests: accepted values, years min ≤ max, and a
  WARN-level check that every posting has an ml.posting_nlp row.
- seniority_source on RDS: title 402 (57%), years 206 (29%), none 96 (14%)
  — "no level" 43% → 14%. seniority_effective (total / salaried): intern
  6/0, junior 48/22, mid 111/50, senior 241/97, staff_plus 163/57,
  manager 39/10, unknown 96/34. `dbt build` PASS=81.
- Since 5.5 nlp_enrich runs in the daily DAG right after load_postgres. A
  reload by hand still needs `python -m src.ml.nlp_pipeline` afterwards;
  otherwise new postings lack years (the WARN test and the ml source
  freshness flag it) and untitled ones fall to 'unknown'.

5.1b Embeddings + topics — built 2026-10-09 (D1–D3 approved that day):
- D1 Long descriptions → chunk + average. all-MiniLM-L6-v2 reads ≤ 256
  word-pieces (~190 words); median description 791 words, 653 of 704 (93%)
  longer. The first 190 words held a median 13% of a posting's skills, and
  40% of postings showed no skill there (company intro, benefits).
- src/ml/embeddings.py (shared with the Phase 6 app): embed_texts() splits a
  text into 150-word chunks (our text averages ~1.3 pieces/word: 150 words
  overflow 1% of chunks, 200 words 55%), embeds each on CPU, averages them
  weighted by words, scales to length 1. Model pinned to revision c9745ed;
  loaded from the local cache first (otherwise ~9 Hugging Face requests per
  load, against an anonymous rate limit).
- Boilerplate filter (nlp_pipeline.strip_shared_sentences): sentences used
  under 3+ different job titles are dropped before embedding (18% of
  description words; no posting emptied). Without it, 3 of 12 topics were a
  single employer (Capital One: 22 postings with identical legal/pay text;
  Google, DoorDash) and others were led by employer benefits text.
- D3 Embeddings → s3://{S3_CURATED_BUCKET}/embeddings/all-MiniLM-L6-v2/
  postings.parquet (job_id, n_chunks, embedding float32[384]; model, revision
  and chunking in the file metadata), overwritten each run; 1.9 MB, ≈ $0.
- src/ml/topics.py: UMAP (30 neighbours, 10 dims, cosine, random_state 42)
  → HDBSCAN (min cluster size 10, "leaf" selection) → c-TF-IDF (1–2 word
  terms, English + generic job stop words, reduce_frequent_words). Keywords
  must be used by ≥ 3 employers (no employer names). Text is cleaned the way
  BERTopic cleans it before that vocabulary is built (a term it never counts
  → division by zero). No min_df: BERTopic counts per TOPIC, so min_df=2
  dropped every word unique to one topic.
- Tuning (4 random seeds per setting): HDBSCAN's default "eom" selection gave
  2–17 topics depending only on the seed (adjusted Rand index between seeds
  as low as 0.02); "leaf" kept 8–9 topics (ARI mean 0.65, min 0.57), at the
  cost of about half the postings unassigned. Min size ≥ 15 merged nearly
  everything into one or two topics.
- D2 Outliers stay "unassigned" (topic -1, probability 0).
- Result (RDS, 704 postings, ~53 s): 9 topics, 332 unassigned (47%); every
  rerun on the same data gave identical topics (704 of 704). Topics (size):
  data engineering (109), software engineering (88), ML engineering (59),
  clinical/health data analysis (33), AI/ML research (23), AI engineering —
  agents, evaluation (21), analytics & dashboards (17), customer/marketing
  insights (12), data-science strategy (10). Data scientist postings cluster
  least: 86 of 123 unassigned.
- ml.topics (topic_id, label, top_words, n_postings) and ml.posting_topics
  (job_id, topic_id, topic_probability) are written in the same transaction
  as ml.posting_nlp → dbt sources → stg_topics, stg_posting_topics (keys,
  relationship, probability in [0, 1]). `dbt build` PASS=91.
- Topic ids are stable only while the data is unchanged; new postings can
  reshape topics. The app shows topics by their words, never a fixed id.
- macOS here sleeps after 1 idle minute (pmset sleep 1): unattended runs
  stalled ~17 min in Maintenance Sleep (pmset log) while the work takes
  ~1.5 CPU-minutes. Manual runs: `caffeinate -i` (no help once the Mac is
  already asleep). Same exposure for 5.5's nightly Airflow runs.

5.2 Salary model (src/ml/salary_model.py):
- Features a resume can provide only: role, seniority_effective (incl.
  unknown), state, remote, the common skills (≥ 10 salaried postings) as
  yes/no, skill_count. No employer, publisher or topic.
- Target log(salary_mid_annual); errors reported in dollars.
- 5-fold cross-validation grouped by employer; MAE overall and per role vs
  baselines: global median, per-role median, per role × seniority median.
  The model is used only if it beats the per-role median, else the app
  falls back to the baseline and says so.
- XGBoost, shallow trees + early stopping. MLflow logs params, CV scores,
  baselines, features and the model.
- Missing-skill impact: what-if (same role/seniority/location + one skill),
  only for skills with enough salaried postings in that role, shown beside
  mart_skill_salary_by_role, worded "associated with".
- Model + feature spec exported to the S3 curated bucket for the app.
- Record the real MAE vs the < $9K target (expected to miss at 270 rows).

5.2 Status: COMPLETE (2026-10-13). Built 2026-10-10; real run 2026-10-13:
- MLflow run da52fa5124ef4a42a1e4962bf58ab418 (Databricks Free Edition,
  experiment /Users/<your Databricks email>/talentsignal-salary): FINISHED;
  13 params, 24 metrics (overall + per-role MAE for the model and the three
  baselines), tag use_model=true, artifacts feature_spec.json +
  model_card.json; the model is an MLflow 3 LoggedModel linked to the run.
- S3 export verified by reading it back: models/salary/model.json (161 KB)
  loads and predicts (e.g. senior data engineer, NY, Python/SQL/Spark/AWS/
  Airflow → $162,700); feature_spec.json (6 KB) carries the same run id,
  use_model=true, 152 trees, 64 features.
- Data (dbt marts): 270 salaried postings, 207 employers (most: Meta 9),
  5 states + 27 with no location, 22 remote; $69K–$450K, median $162K.
- src/ml/features.py (shared with 5.4 / the app, no PyTorch): Profile →
  build_features(): 64 columns = role (5) + seniority_effective (6, incl.
  unknown) + state (5 + unknown; unseen states/levels → unknown) + remote +
  45 skills yes/no (≥ 10 training postings, chosen inside each CV fold) +
  skill_count (all dictionary skills). Unknown role → ValueError.
- XGBoost on log(salary): depth 3, learning rate 0.05, subsample and
  column sample 0.8, min_child_weight 3. Trees per fold by early stopping on
  20% of the fold's employers (40–190); final model = median (152).
- Grouped 5-fold CV (by employer), MAE in dollars, out of fold:
  model $34,236 | role × seniority median $37,097 | role median $41,231 |
  global median $48,954. Per role (model vs role median): data analyst
  $23.7K vs $26.8K, data engineer $26.3K vs $37.1K, data scientist $41.2K
  vs $51.9K (role × seniority $40.2K is better here), ML engineer $40.9K vs
  $46.0K, software engineer $41.8K vs $46.8K.
- 5 random splits: model $33.4K–$35.9K vs role median $41.2K–$42.3K
  (role × seniority $36.1K–$38.3K): beats the role median every time →
  use_model = true. Target < $9K MISSED: MAE ≈ 21% of salary (median
  absolute error $26K); ~270 rows can't support it.
- What-if (skill_impact): predicted change when one skill is added
  (skill_count +1), only for skills in ≥ 5 salaried postings of the role
  (what_if_skills; same floor as mart_skill_salary_by_role). E.g. analysts
  dbt +$15K, Excel −$6K; ML/software engineers C++ +$14–16K; software
  engineers Git −$27K (Git comes with junior/generalist postings).
  Associations, not causal — UI wording "associated with".
- MLflow (_log_to_mlflow): params, CV MAE overall + per role for model and
  baselines, use_model tag, feature_spec.json, model_card.json, the model.
  The S3 export runs only after logging succeeds: s3://{S3_CURATED_BUCKET}/
  models/salary/model.json (XGBoost JSON) + feature_spec.json (spec, what-if
  skills, baseline medians for the fallback, CV MAE, use_model, run id).
- Tests use a throwaway local MLflow store; MLflow 3.17 refuses plain-folder
  stores unless MLFLOW_ALLOW_FILE_STORE=true (tests only).

5.3 Demand forecast (src/ml/demand_forecast.py):
- Series: per role × skill, share of that role's collected postings per
  collection week mentioning the skill, zero-filled.
- Gate: forecast only series with ≥ 12 weekly points; otherwise output
  insufficient_history + the observed share. Prophet: linear trend, no
  seasonality, wide intervals; backtest vs "next week = this week" once
  ≥ 16 weeks. The 90-day horizon only for series that pass the gate.

5.3 Status: BUILT (2026-10-13); no series passes the gate yet.
- python -m src.ml.demand_forecast reads analytics_marts.mart_skill_demand
  (role × skill × collection week share; unsampled weeks are gaps) and
  rebuilds ml.skill_demand_forecast (replace_tables, one transaction).
- < 12 weekly points → one 'insufficient_history' row with the latest
  observed week + share. ≥ 12 → 13 weekly rows (91 days ≥ the 90-day
  horizon): Prophet with linear trend, no seasonality, 95% intervals, shares
  clipped to [0, 1], numpy seed fixed (Prophet samples its intervals) so
  reruns match. ≥ 16 points → one-step-ahead backtest over the last 4 weeks:
  backtest_mae_prophet vs backtest_mae_naive ("next week = this week").
- Real data (2026-10-13): 390 series, ALL insufficient_history — only 2 collection
  weeks exist (2026-09-28 for every role, 2026-10-05 for data engineer);
  293 series have 1 point, 97 have 2. Forecasts need ≥ 12 weeks of weekly
  collection: the daily DAG has been ON since 2026-10-13 (needs Airflow
  running + the Mac awake at 22:00 UTC) → first forecasts ~12 weeks later.
- dbt: source ml.skill_demand_forecast → stg_skill_demand_forecast; tests:
  unique role|skill|week, accepted statuses, row consistency (forecast rows:
  week after the last observed, 0 ≤ lower ≤ forecast ≤ upper ≤ 1;
  insufficient rows: no forecast columns). `dbt build` PASS=98.
- Tests: synthetic series — gate, 13 Mondays continuing a rising trend,
  clipping of a falling series, backtest (Prophet beats naive on a clean
  trend; naive MAE exactly 0.01), identical reruns. ~0.6 s per Prophet fit.

5.4 Resume features (src/ml/resume_features.py), called by Phase 6:
- extract_text(pdf_bytes): pdfplumber, in memory only; no text → clear error.
- find_skills(text): the shared dictionary.
- build_features(skills, role, seniority, state, remote): the SAME function
  training uses (no training/serving skew). Test fixture: a small made-up
  text-based PDF.

5.4 Status: BUILT (2026-10-13).
- src/ml/resume_features.py: extract_text(pdf_bytes) — pdfplumber on an
  in-memory buffer, first 10 pages (caps huge uploads); non-PDF bytes →
  ValueError "isn't a readable PDF"; no text → NoTextError ("Scanned or
  image-only resumes aren't supported…", shown as is by the app).
  find_skills = the shared dictionary (re-exported). build_features(skills,
  role, seniority, state, remote, spec) wraps features.build_features — the
  training function — with the spec from the exported feature_spec.json.
- Fixture: tests/fixtures/resume_sample.pdf (934 bytes, made up), written by
  make_resume_pdf.py (a hand-built one-page PDF; a test checks they match).
  Extracts all 7 lines; skills: Python, SQL, Spark (from "Apache Spark" /
  "PySpark"), Airflow, AWS, dbt, Docker, PostgreSQL.
- Tests: extraction, skills, same features as training, scanned/no-text and
  non-PDF errors, and a privacy guard (extract_text never opens a file for
  writing).
- Carry to Phase 6: the app process will load PyTorch (resume embedding for
  matching) AND XGBoost (salary) — the 5.6 OpenMP rule. Verify on the Linux
  server, or embed in a separate process.

5.5 Airflow: … load_postgres → nlp_enrich → dbt_source_freshness →
dbt_build → train_salary_model → forecast_demand (update test_dags.py).

5.5 Status: BUILT (2026-10-13) — the user's "5.5" (nlp_enrich + forecast_demand) and
"5.6" (salary model after dbt) in one change.
- talentsignal_pipeline (9 tasks): fetch_jobs → clean_jobs → extract_skills
  → load_postgres → nlp_enrich → dbt_source_freshness → dbt_build →
  {train_salary_model, forecast_demand}. The two models branch off
  dbt_build instead of chaining (spec sketch): both read dbt marts but not
  each other, so a failed salary run (e.g. Databricks down) doesn't block
  the forecast. They do run in parallel (see Phase 4 local runtime); they
  are separate processes, so that is safe.
- One process per task (BashOperator → .venv/bin/python -m …) keeps
  PyTorch (nlp_enrich) and XGBoost (train_salary_model) apart (5.6 rule).
- Timeouts: nlp_enrich 45 min (~1 min awake), train_salary_model 30 min,
  forecast_demand 45 min (seconds now; ~20 min once ~390 series forecast +
  backtest). Retries: the DAG default (1 after 5 min).
- tests/test_dags.py: chain + branch structure (both models depend only on
  dbt_build, nothing after them) and each ML task's exact command; 11 pass.
- Verified with `airflow tasks test` (run_local.sh environment, no
  scheduler, no JSearch): nlp_enrich 57 s (same outputs as by hand);
  train_salary_model logged MLflow run b1b028edc59847da9da04d914828a7ef and
  re-exported the same model (the S3 card now names this run);
  forecast_demand wrote 390 insufficient_history rows.
- 5.7 deliverable MET 2026-10-13: DAG unpaused → the latest missed slot
  (scheduled__2026-10-12T22:00) ran all 9 tasks green in 3 min 31 s:
  fetch_jobs 25.9 s, clean_jobs 30.4, extract_skills 29.8, load_postgres
  24.3, nlp_enrich 56.8, dbt_source_freshness 4.2, dbt_build 10.7, then in
  parallel train_salary_model 22.1 and forecast_demand 2.9. Fetched 30 data
  scientist postings (NY) with 3 JSearch requests (RapidAPI: 115 left);
  postings 704 → 731 (283 salaried); salary CV MAE $34,297; MLflow run
  478031886bae40aaabfb6b4ddd513815; 393 demand series, all
  insufficient_history. The DAG stays ON.
- Mac sleep (pmset sleep 1) stalls tasks mid-run; an option is to start
  Airflow under `caffeinate -i` in run_local.sh (keeps the Mac awake while
  Airflow runs) — not done, the user's call.

5.6 Dependencies (installed 2026-10-09): spaCy, sentence-transformers
(PyTorch), BERTopic, XGBoost, Prophet, scikit-learn, mlflow-skinny (client
only: tracking is hosted on Databricks; 11 MB vs 78 MB for full mlflow),
pdfplumber as the `ml` dependency group. AWS cost $0.
- requirements-ml.txt = dev + ml, one lock (seeded from requirements-dev.txt,
  so shared pins are identical); the laptop installs it (.venv +1.5 GB).
  requirements-dev.txt stays lean for the CI pytest job (ML tests skip there).
- CI `ml` job: CPU-only PyTorch from download.pytorch.org/whl/cpu (196 MB vs
  ~1.55 GB with NVIDIA libs), version read from requirements-ml.txt, then the
  lock with --no-deps (the lock is compiled on macOS; resolving again on Linux
  pulls XGBoost's 352 MB nvidia-nccl-cu12), then tests/test_ml.py,
  test_nlp.py, test_embeddings.py, test_topics.py, test_features.py,
  test_salary_model.py, test_demand_forecast.py and test_resume_features.py. The embedding model
  (~90 MB) is cached by actions/cache, keyed on src/ml/embeddings.py (which
  pins its revision).
- CI `dbt` job pulls postgres:18 from Amazon's ECR Public mirror
  (public.ecr.aws/docker/library/postgres): Docker Hub's anonymous pull
  limit on shared runner IPs failed the job twice (2026-10-09).
- macOS: XGBoost needs OpenMP (`brew install libomp`).
- RULE: PyTorch and XGBoost run in SEPARATE processes. PyTorch bundles its own
  OpenMP; loaded before multi-threaded XGBoost in one process → segfault (exit
  139). salary_model.py must never import torch/sentence-transformers; Airflow
  tasks are separate processes anyway. tests/conftest.py sets
  OMP_NUM_THREADS=1 (tiny data), and a subprocess regression test guards it.
- en_core_web_sm: not installed yet — the 5.1 years matcher only needs
  spacy.blank("en") (like_num handles "four"); add the model only if 5.1's
  phrase review list needs noun chunks.

5.7 Deliverable: DAG green end to end; CLAUDE.md records the real salary
MAE vs baselines, forecast status, topic count and years-extraction
coverage; unit tests (years cases, feature builder, gate, baselines, PDF
text / no text); dbt CI fixture gains an ml.posting_nlp sample.

### Phase 6 — Streamlit app + EC2 hosting
Plan approved 2026-10-13 (decisions D1–D6 below; build order at the end).

App direction (set 2026-10-04): a resume intelligence tool, not a generic
market dashboard.

Docker (decided 2026-10-06): not used for Airflow in Phase 4; it belongs
here, e.g. containerizing the app for EC2 (infra/docker-compose.yml).

- Page 1 — Resume Analyzer (was Market Overview). User uploads a resume PDF;
  text extracted with pdfplumber; skills found with regex + keyword matching
  using the same skill dictionary as src/processing/extract_skills.py
  (no LLM). Shows:
  - Skills found on the resume + how often each appears in real postings
  - Match % against each target role
  - Predicted salary (XGBoost model from Phase 5)
  - Top 3 missing skills with estimated salary impact
  - Real matching job postings from this week
- Page 2 — Salary Explorer
- Page 3 — Skill Demand Forecast
- Page 4 — Job Insights

Decisions:
- Skill dictionary shared without Spark: done in Phase 5.0 as
  src/skills/dictionary.py (the app server has no PySpark/Java).
- Resumes are personal data: parse in memory only; never write uploads or
  their text to disk, S3 or logs.
- Text-based PDFs only (no OCR); a scanned/image-only PDF yields no text →
  show a clear message instead of an empty analysis.

Decisions (2026-10-13):
- D1 Matching postings: embeddings. The resume is embedded with the same
  pinned all-MiniLM-L6-v2 + embed_texts() as the postings (5.1b) and ranked
  by cosine similarity; shared skills are shown as the "why". Costs PyTorch
  on the server (~+1 GB image, ~0.5 GB RAM of the t3.small's 2 GB). OpenMP
  rule: the app predicts with XGBoost single-threaded (n_jobs=1).
- D2 Match % = demand-weighted coverage: over the skills in ≥ 10% of a
  role's postings (13–30 per role), sum of the shares of those on the
  resume ÷ sum of all their shares; the page lists which skills counted.
- D3 Top 3 missing skills = the most in-demand ones the resume lacks; each
  shows the model what-if (if in what_if_skills) and the within-role
  median difference (mart_skill_salary_by_role, if enough salaries),
  worded "associated with" (not causal).
- D4 HTTPS on a free sslip.io hostname for the Elastic IP
  (e.g. 3-15-22-7.sslip.io resolves to 3.15.22.7) with a Let's Encrypt
  certificate via nginx; no domain purchase. Plain HTTP is not acceptable
  for resume uploads.
- D5 Deploy via GitHub OIDC → AWS SSM Run Command: no SSH port open to the
  internet; the user creates the IAM role for GitHub in the console.
  REVISED 2026-10-15 (user's choice): the account is a member of an AWS
  Organization whose SCP explicitly denies iam:CreateOpenIDConnectProvider (and
  CreateSAMLProvider), so GitHub OIDC is impossible. Instead the server pulls: CI
  publishes the images to GHCR; a systemd timer on the server deploys the newest
  release (infra/deploy/update.sh). No AWS credentials in GitHub, no SSH; SSM Run
  Command (ts-admin from the laptop) only for the first / manual deploys.
- D6 Docker: the app (and nginx) in Docker Compose, started by systemd.
- D7–D10 (2026-10-14, the user pivoted the UI from Streamlit): D7 Next.js as a
  static export served by nginx, which proxies /api to the API (no Node
  process on the 2 GB server); D8 FastAPI (typed models, OpenAPI → TS
  types); D9 shadcn/ui + Recharts + Lucide on Tailwind (one design system;
  no Tremor); D10 the Streamlit pages (PR #12, already merged) removed and
  their non-UI code moved into src/api.
- "This week's postings" = fetched in the last 7 days; when a role has
  none, the latest collection, labelled with its date (the free JSearch
  plan refreshes each role about every 5 days).

Dependencies (approved 2026-10-13):
- (2026-10-14: streamlit swapped for fastapi>=0.143,<0.144 + uvicorn>=0.54,<0.55;
  laptop lock back to 165 packages, server lock 68, identical pins.)
- pyproject `app` group: streamlit>=1.65,<2 + pyarrow>=25,<26 (the
  embeddings Parquet; until now only via PySpark in dev). Streamlit 1.65.0
  fits every existing pin: requirements-ml.txt (laptop) 165 → 173 packages,
  no version changes.
- requirements-app.txt (server image), compiled from requirements-app.in
  (the app's 10 direct imports) seeded from requirements-ml.txt: 77
  packages, every version identical to the laptop lock; no dbt, MLflow,
  PySpark, Prophet, BERTopic or spaCy. Not compiled from pyproject: that
  always adds the base deps (dbt). The image installs CPU PyTorch, then
  `pip install --no-deps -r requirements-app.txt` (as the CI ml job).
- Serving code must not import salary_model.py (MLflow): predict_salary +
  skill_impact move to a light serving module (build step 3).
- pip-tools quirk: lock headers print `--no-index` for
  --no-emit-index-url; resolution still uses PyPI.

Estimated AWS cost (on-demand list, us-east-2; confirm before creating):
EC2 t3.small $15.18/month + EBS gp3 20 GB $1.60 + Elastic IP $3.65 +
transfer ~$0 ≈ $20.43/month (≈ $38/month with RDS). sslip.io: $0.

Build order: 0 DAG on + one green 9-task run (done 2026-10-13) → 1 app
dependencies → 2 data layer (read-only DB user app_reader, cached RDS
queries, S3 loaders, new mart_role_skill_profile) → 3 app logic as tested
pure functions → 4 four pages + Streamlit AppTest; the user tries it
locally → 5 Docker image + compose (nginx) → 6 AWS after cost confirmation
(EC2, Elastic IP, security groups, S3-read instance role, EC2 → RDS rule,
HTTPS) → 7 systemd + nginx (websockets, upload size, rate limit) → 8 CI/CD
(app tests on PRs; build → GHCR → deploy via OIDC + SSM on merge) → 9
public smoke test, docs, resume bullet.
(Revised 2026-10-14: step 4 = FastAPI API + Next.js static frontend in web/; step 5's
image runs the API, and nginx serves web/out/ and proxies /api/.)

Step 2 Status: BUILT (2026-10-13) — data layer.
- app_reader (src/app/db_setup.py, re-runnable, one transaction): LOGIN,
  SELECT-only on analytics_staging / _intermediate / _marts and ml; every
  session read-only by default; statement_timeout 30s; ALTER DEFAULT
  PRIVILEGES FOR the owner so tables dbt and the ML steps re-create stay
  readable. Password generated into .env (APP_DB_PASSWORD), passed as a
  query parameter. On RDS, NOSUPERUSER can't be named by a non-superuser
  (left out; roles are created without it).
- Verified as app_reader: reads all 4 schemas, incl. mart_role_skill_profile
  created by dbt AFTER the setup (default privileges work); raw.* →
  permission denied; DELETE / CREATE TABLE → read-only transaction.
- dbt mart_role_skill_profile: per role × skill — n_postings_with_skill,
  share_of_role_postings, demand_rank (unique per role) + the within-role
  salary comparison from mart_skill_salary_by_role (salary_sample_status).
  393 rows; 13–30 skills per role in ≥ 10% of postings (D2's basis).
  Tests: unique keys, relationship to dim_role, statuses, shares in [0, 1].
  `dbt build` PASS=106.
- src/app/data.py (no Streamlit/PyTorch/XGBoost imports): ThreadedConnectionPool
  (max 4) as app_reader, autocommit SELECTs, broken connections discarded;
  ttl_cache (1 h, thread-safe, deep copies; nested skills are tuples and
  embedding rows read-only). postings() (731 × 23: role, location, skills,
  salary, seniority, topic, apply link), skill_demand(), salary_bands(),
  job_insights(); S3 via boto3's default credentials (.env keys on the
  laptop, the instance role on EC2): salary_model_json(),
  salary_model_card(), posting_embeddings() (+ file metadata in attrs).
- src/ml/artifacts.py holds the S3 keys; salary_model.py uses it and a
  test checks nlp_pipeline's embeddings key matches.
- Real smoke test caught pandas 3 turning NULL topic keywords into NaN
  (truthy) — fixed and covered by a test.
- FINDING for Page 4: the 2026-10-13 run (+27 postings) reshuffled the
  topics: unassigned 47% → 52%, data engineering 109 → 50 postings, noisy
  topics ("ago", "mcdonalds" keywords). Stabilise before Job Insights.

Step 3 Status: BUILT (2026-10-13) — app logic as tested pure functions.
- src/app/serving.py: predict_salary + skill_impact moved from
  salary_model.py (training keeps what_if_skills) + load_model(model_json)
  (single-threaded). Importing it loads XGBoost (+ scikit-learn via
  XGBRegressor), never MLflow, PyTorch or Streamlit.
- src/app/logic.py: core_skills / match_pct (D2), top_missing_skills (D3),
  predict_salary_for_resume, match_postings (D1). Additions to the agreed
  signatures (keyword-only, defaulted): top_missing_skills takes seniority /
  state / remote (the what-if needs a profile); match_postings takes
  resume_skills (shared skills) and now (tests). Salary range = ± the
  role's CV MAE (overall when none); role median when use_model is false.
  "This week" = fetched in the last 7 days, else the role's latest
  collection (frame.attrs window / since). Embeddings from another model
  revision are refused (EMBEDDING_MODEL_NAME / _REVISION now live in
  artifacts.py; embeddings.py imports them).
- CRASH FOUND + FIXED: in the app process, XGBoost imported before PyTorch
  → PyTorch's multi-threaded OpenMP segfaulted (exit 139) while embedding,
  even with XGBoost on 1 thread; OMP_NUM_THREADS=2 still crashed, 1 works.
  src/app/__init__.py pins OMP_NUM_THREADS=1 before any app module loads
  either library (the Docker image will set it too). Cost: a 2-page resume
  embeds in 0.25 s single-threaded. Regression test: a fresh process with
  the variable unset embeds + trains/predicts XGBoost → exit 0.
- Real smoke test (made-up resume fixture, real RDS/S3/model): skills
  Python, SQL, Spark, Airflow, dbt, PostgreSQL, AWS, Docker; match % 23–36%
  (data engineer: 6 of 30 core skills); missing ETL, Machine Learning,
  Data Modeling; salary (model, mid, TX) $143,669 ± $27,605 vs role median
  $162,500; matches 0.70–0.74 similarity from the last 7 days with shared
  skills; analyst / software engineer fall back to the Oct 3 collection.
- For the page: the model's what-if is often ~$0 (shallow trees rarely
  split on those skills) while within-role medians differ by thousands —
  word $0 as "no measurable effect in the model".

Step 4 Status: BUILT (2026-10-13) — the five Streamlit pages; SUPERSEDED 2026-10-14
(Streamlit removed; see the API status below).
- Pages run as separate scripts (pages/ folder) and each starts with
  `from src.app import ui` (pins OMP_NUM_THREADS first). Home: overview,
  links, data freshness (postings, newest collection age, last 7 days,
  model MAE; warning when > 2 days old). Resume Analyzer: upload or "Try a
  sample resume" (made-up PDF), target role / level / state / remote →
  skills found with their share of the role's postings, match % for all
  roles + the core skills that counted, salary ± role CV MAE next to the
  role median, top 3 missing skills (model what-if + within-role median
  with n), top 10 matching postings with apply links and which window was
  used. Salary Explorer: percentiles by level / state (< 5 → too few) vs
  BLS (chart + table). Skill Demand: ranked skills, progress toward 12
  weekly collections, forecast chart once a series qualifies. Job
  Insights: topics with keywords and unassigned share, role mix heatmap,
  level mix, remote share.
- Wording: money to the nearest $1,000, half up (Python's round() is
  half-even: $14,500 showed as $14,000); a what-if under $500 reads "no
  measurable effect"; missing numbers (None or NaN) read "—" — the
  real-data check had silently shown "$nan" for data analyst's BLS median.
- Privacy: the resume is read from the upload in memory, never cached
  (no st.cache on resume data), saved or logged; .streamlit/config.toml
  caps uploads at 5 MB, turns off usage stats and hides error details
  from visitors (showErrorDetails = "none"; AppTest sees the redacted
  message too).
- Tests: AppTest drives every page on stub data (tests/app_stubs.py: no
  DB, S3 or embedding model; tiny real XGBoost): real uploads of the
  fixture PDF, a scanned (no-text) PDF, a non-PDF, the sample button, a
  role with no recent postings, filters down to "too few", the forecast
  chart branch, and the $0 → "no measurable effect" wording. Plus
  formatting and the salary-band / topic-mix helpers.
- Real data: every page renders with no exceptions or errors (AppTest
  against RDS + S3). Run locally: infra/app/run_local.sh →
  http://localhost:8501 (localhost only).
- Tried on the user's own resumes (7 versions, 2026-10-14): text extracted from
  all, 14–45 skills each, best matches data scientist / data analyst
  (77–95%). Found: (1) junior salary estimates read high — a junior data
  analyst got ~$121K vs a $79K posted junior median: the model barely
  separates levels and pulls toward the average (skill_count was ruled
  out: 5→45 skills moved it ~$100); (2) matches ignored level (Senior / VP
  roles for a junior); (3) with/without medians from 7–10 postings swung
  ±$33K. NOTE: those AppTest runs silently kept state = CA (setting the
  selectbox to None didn't take); state=CA reproduces the $129K reported.

API Status: BUILT (2026-10-14) — Streamlit → FastAPI (PR B adds the Next.js web/).
- src/app → src/api (git mv: data, logic, serving, db_setup, __init__);
  Streamlit pages, ui.py, formatting.py, .streamlit/, infra/app removed.
- Endpoints (src/api/main.py; docs at /api/docs): GET /api/health (no
  backend), /api/options (roles, levels with labels, states), /api/overview
  (freshness), /api/salaries?level&state, /api/skills?role,
  /api/forecast?role&skill, /api/insights; POST /api/analyze?role&level
  &state&remote with the raw PDF as the body.
- Resume privacy: raw body (no multipart → FastAPI never spools it to a
  temp file, which it does above 1 MB); read in memory with the 5 MB cap
  enforced while streaming; the response never contains the text; nothing
  saved or logged. CPU work runs in a worker thread (run_in_threadpool).
- Errors: 415 not a PDF, 413 > 5 MB, 400 empty / unreadable PDF, 422 no text
  (scanned) / unknown role / unknown level, 404 missing forecast series,
  503 backend down — plain messages + a code, never internals.
- Statuses carry the decisions (frontend only formats): model_impact_status
  (value | no_measurable_effect under $500 | not_enough_data),
  median_difference_status, level_median.status.
- Fixes (logic.py): (1) level_salary → the posted median for role × level
  with n, shown beside the estimate (junior data analyst: $79,200, n=5);
  (2) match_postings ranks postings within one step of the user's level
  first (LEVEL_RANK; unknown = near) and returns level + near_level;
  (3) a with/without median difference needs ≥ 10 salaries on each side
  (MIN_SALARIES_PER_SIDE; e.g. Data Modeling 9 vs 54 → hidden).
- Real-data run caught a stale pooled connection (first request after
  idle → 503): data._query now retries once on a fresh connection.
- Real data (localhost:8000): every endpoint 200; cached reads 4–36 ms;
  analyze 0.84 s. Error cases verified with curl.
- Tests: test_api_routes.py (TestClient on stubs: every endpoint, all error
  codes, upload cap, no resume text in the response), fix tests in
  test_api_logic.py, retry test in test_api_data.py. CI job "API tests
  (server lock)" installs exactly CPU PyTorch + requirements-app.txt.
- Follow-ups: Starlette deprecates httpx for TestClient (install httpx2
  when it stops working); retrain the salary model to weigh level (fix 1
  only shows the gap).

Frontend Status: BUILT (2026-10-14) — web/ (PR B).
- Next.js 16.4 (App Router, Turbopack), React 19.3, TypeScript 5, Tailwind 4,
  shadcn/ui 4.21 ("base-nova" style on Base UI primitives, not Radix),
  Recharts 3, Lucide 1.56; scaffolded with create-next-app 16.4.
- Static export: output "export", trailingSlash (each page = a folder with
  index.html, no nginx rewrites), images.unoptimized; create-next-app's
  cacheComponents / partialPrefetching removed (they need a Node server).
  All data is fetched in the browser; NEXT_PUBLIC_API_BASE is empty in
  production (same origin, nginx proxies /api) and http://localhost:8000
  in web/.env.development (committed; un-ignored in web/.gitignore).
- Pages: Home (overview KPIs, pipeline status, links, how it works);
  Resume Analyzer (drop zone with client-side PDF/size checks, role / level
  / state / remote — changing them re-runs on the same file, "Try a sample
  resume", results: KPIs, match by role, salary vs posted medians for the
  level and the role, skills found, core-skill coverage, 3 skills to add
  worded from the API's statuses, matching postings with level badges and
  apply links); Salary Explorer (level/state filters, a plain-HTML range
  chart p25–p75 + median + BLS, table, too-few note); Skill Demand (top-12
  bar chart, ranked table, forecast progress, Prophet chart once a series
  qualifies); Job Insights (topic cards, role mix and level mix stacked
  charts, remote share).
- Types can't drift: src/api/export_openapi.py writes web/openapi.json;
  `npm run gen:api` (openapi-typescript) writes src/lib/api-types.ts.
  test_api_routes.py fails if openapi.json is stale; the CI web job fails
  if api-types.ts is.
- Tests (Vitest 5 + Testing Library): format rules, the API client (raw PDF
  body, query string, error mapping), the results view, the range chart —
  16 pass. happy-dom, not jsdom: jsdom 27 needs require(esm) (Node ≥ 20.19 /
  22.12) and the laptop runs Node 20.17.
- CI job "Web": Node 24 LTS, npm ci, lint, type-check, generated types
  current, tests, static build; NEXT_TELEMETRY_DISABLED=1.
- npm audit: the shipped dependencies have 0 known vulnerabilities (the
  shadcn CLI moved to devDependencies: only its CSS is used, at build time).
  9 "high" remain in dev tooling (shadcn CLI, eslint-config-next) via one
  braces advisory with no patched release; `npm audit fix --force` would
  downgrade eslint-config-next to v14 — not done. Recheck later.
- Local machine: Node 20.17 is the x86-64 build under Rosetta (slower) and
  past end of life (2026-04); upgrading to arm64 Node 24 LTS is recommended
  (the user's call). The dev server binds 127.0.0.1 (it was on the LAN);
  infra/api/run_local.sh allows both localhost:3000 and 127.0.0.1:3000.
- web/AGENTS.md is written by Next.js itself (bundled-docs pointer); kept.

Step 5 Status: BUILT (2026-10-15) — Docker, local (no AWS yet).
- Two images, both built from the repo root with allowlist build contexts
  (infra/docker/*.Dockerfile.dockerignore: `*` then the needed files; .env can't
  reach an image):
  - api (infra/docker/api.Dockerfile): python:3.11-slim; ENV OMP_NUM_THREADS=1
    (non-negotiable, also pinned in src/api/__init__.py); libgomp1 for XGBoost;
    CPU PyTorch then requirements-app.txt, both --no-deps (the user's notes
    called it requirements-server.txt — the server lock is requirements-app.txt);
    all-MiniLM-L6-v2 at its pinned revision baked in at build (HF_HOME=/opt/hf,
    HF_HUB_OFFLINE=1: no Hugging Face calls at run time); non-root user; one
    uvicorn worker; healthcheck on /api/health.
  - web (infra/docker/web.Dockerfile): node:24-slim runs npm ci + next build →
    web/out/ copied onto nginx:1.30-alpine. An image (not a mounted web/out/)
    because the server has no Node: EC2 pulls both images from GHCR, so the CD
    job (step 8) pushes talentsignal-web next to talentsignal-api.
- infra/docker/nginx.conf: static pages (trailingSlash folders, 404.html,
  /_next/static cached for good, HTML revalidated); /api/ → api:8000; security
  headers. /api/analyze: 6 MB cap (the API's 5 MB check answers first),
  client_body_buffer_size 6m + proxy_request_buffering off so a resume is never
  written to nginx's disk (its default spills bodies > 16 KB to a temp file);
  rate limit 20/min per visitor, burst 10. nginx's own 413 / 429 / 502–504 answer
  in the API's {detail, code} JSON, which the frontend shows.
- infra/docker-compose.yml: api (not published; expose 8000) + web
  (${WEB_BIND:-127.0.0.1}:${WEB_PORT:-80}:80; server: WEB_BIND=0.0.0.0). The api
  container gets only the 9 variables it reads (RDS_HOST/PORT/DB, APP_DB_USER/
  PASSWORD, AWS_REGION, S3_CURATED_BUCKET + laptop-only AWS keys; on EC2 the
  instance role) — never RDS_USER/RDS_PASSWORD, RAPIDAPI_KEY or DATABRICKS_TOKEN.
- infra/docker/run_local.sh: checks .env and Docker, then `compose up --build
  --wait` → http://localhost/ (docs /api/docs).
- Verified locally (2026-10-15, Colima, arm64): both images build in ~2 min
  (cold); api image ~2.2 GB uncompressed (pip 1.9 GB: torch 656 MB, xgboost 227,
  pyarrow 143, scipy 122, transformers 120; model 92 MB) — web 104 MB. Through
  nginx: health, pages, 301 /analyze → /analyze/, 404 page; /api/overview from
  RDS as app_reader (1.1 s cold); sample resume analyzed in 0.99 s; 415 non-PDF,
  413 at 5.5 MB (API) and 7 MB (nginx, JSON), 429 after the burst; 0 files in
  nginx's temp dirs after uploads; no resume text in logs; OMP_NUM_THREADS=1, user
  app; API 768 MiB RAM after an analysis (t3.small: 2 GB → add swap on EC2); the
  image embeds with --network none.
- Possible later saving (needs approval: dependency change): xgboost-cpu on the
  server (CPU-only build, far smaller than xgboost's 227 MB).
- To check on EC2: nginx sees the real client IP (locally every request comes from
  the Docker gateway, so the per-visitor rate limit can't be tested here).
- CI job "Docker build (API + web images)": builds both (linux/amd64, GHA layer
  cache, not pushed), runs the API image with --network none (OMP, imports,
  offline model), then compose up → health, pages, 404. tests/test_docker.py
  guards the OMP pin, allowlists, every module the API imports being in the
  image (walks src/api's imports), the api environment and nginx's no-disk
  settings.
- Laptop Docker: Colima 0.10 (Homebrew: colima, docker, docker-compose,
  docker-buildx; ~/.docker/config.json → cliPluginsExtraDirs), VZ VM 2 CPU /
  4 GB / 40 GB. FOUND: this Mac's launchd SSH agent hangs (`ssh-add -l` never
  answers), which stalled Colima's start at "Waiting for … ssh" (VZ and QEMU
  alike). Start it with `SSH_AUTH_SOCK= colima start`. The agent hang affects
  any ssh on this Mac; fixing it is the user's call.

Step 6 Status: BUILT + VERIFIED (2026-10-15) — AWS server (the user's "Step 2").
- Cost confirmed by the user ("fine for a week of learning"): EC2 t3.small $15.18 +
  EBS gp3 20 GB $1.60 + Elastic IP $3.65 ≈ $20.43/month (≈ $38 with RDS).
- Access: talentsignal-dev stays S3-only (it can't describe EC2/RDS/IAM). Infra runs
  with temporary console credentials: `aws login --profile ts-admin` (CLI v2.38; the
  session is the AccountFullAccessRole role, not root). No long-lived admin keys.
- Scripts (infra/aws/, re-runnable, reuse what exists; guarded by
  tests/test_aws_scripts.py):
  - create_server.sh: security group talentsignal-web (80 + 443 from anywhere, no 22);
    RDS security group += 5432 from talentsignal-web; IAM role + instance profile
    talentsignal-ec2 (AmazonSSMManagedInstanceCore + inline app-read: s3:GetObject on
    models/salary/* and embeddings/* of talentsignal-curated-ash, ssm:GetParameter* on
    /talentsignal/app/*); EC2 t3.small AL2023 x86_64 in RDS's VPC/AZ (default VPC,
    us-east-2b), 20 GB gp3 encrypted, IMDSv2 hop limit 2, CPU credits standard, no
    auto public IP, key pair talentsignal-key (emergency only); its own Elastic IP.
  - user_data.sh (first boot): waits for the internet, 2 GB swap (swappiness 10),
    Docker (AL2023 package) with logs capped 3 × 10 MB, Compose v5.6.0 plugin
    (sha256-verified), /opt/talentsignal.
  - put_app_params.sh: the 7 values the API reads → /talentsignal/app/* (String;
    APP_DB_PASSWORD SecureString via aws/ssm), each through a private temp file. Not
    "all of .env" (the user's first plan): the admin RDS password, RapidAPI key,
    Databricks token and talentsignal-dev's keys stay off the server.
  - verify_server.sh: via SSM Run Command only (no secrets in command text or output).
- FOUND: the account's only Elastic IP (18.227.174.211) is RDS's public address (on
  an amazon-rds network interface; the endpoint resolves to it) — not a spare one.
  Left untouched; the server got a new Elastic IP (user approved). create_server.sh
  only ever uses an address tagged Name=talentsignal-app.
- Server: i-0b5ccbfa127db4eb2, Elastic IP 77.113.138.96 → HTTPS host (step 7)
  77-113-138-96.sslip.io. SSM agent Online ~3 min after launch.
- Verified 2026-10-15: bootstrap done; Docker 25.0.16, Compose v5.6.0, 2 GB swap,
  1.47 GB RAM available before the app; role talentsignal-ec2; 7 parameters; from
  inside a container: S3 head-object on the model card (instance role through IMDSv2,
  2 hops) and RDS as app_reader over SSL (`app_reader|731`) through the security-group
  rule; from the laptop: http://77.113.138.96/ → 200 (throwaway nginx), port 22
  closed; the container saw the laptop's real IP (108.91.76.240), so nginx's
  per-visitor rate limit works on EC2 (Docker's port mapping keeps the client IP).
- The app isn't running on the server yet: images reach GHCR with the deploy job.

Steps 7–8 Status: BUILT + LIVE (2026-10-15) — HTTPS, deploy script, CD (the user's Steps 3–5).
- LIVE at https://77-113-138-96.sslip.io/ (commit 1a8d252, PR #18). First deploy over
  SSM in 83 s: images pulled, Let's Encrypt certificate (intermediate YE2, valid to
  2027-01-13; staging dry run first), nginx switched to HTTPS, systemd units installed;
  disk 6.3 GB used / 14 GB free; API 575 MiB RAM, 933 MB available.
- CI on main: publish 47 s (layer cache; both packages public: anonymous pull check
  passed), release job saw the live commit and the public smoke test passed from
  GitHub's runner: health, Let's Encrypt certificate, 301 http → https, HSTS, pages,
  731 postings from RDS, sample resume → 8 skills, $134,979, 10 postings. Same result
  from the laptop. Timers: update every 2 min (no-op run 1.2 s CPU); renewal twice a
  day.
- Fixed after the first deploy: smoke_test.sh tolerated LibreSSL's s_client exit 1 on
  macOS (handshake fine); deploy.sh's settings count missed S3_CURATED_BUCKET (digit
  in the name; the value was always written).
- FOUND on main (PR #19's CI): `compose up --wait` returned as soon as the web
  container ran (no healthcheck), and the next curl hit nginx before it listened
  (connection reset; the PR run passed by timing). Fix: /healthz on port 80 in every
  mode + HEALTHCHECK (start interval 1 s) in the web image, so --wait means "serving";
  5/5 immediate requests after up --wait OK locally. Same race existed in deploy.sh.
- ts-admin sessions expire (~hours): `aws login --profile ts-admin --region us-east-2`
  again before SSM work. Deploys themselves need no AWS login.
- HTTPS (Let's Encrypt, $0): certbot in its own container (certbot/certbot:v5.8.0),
  webroot challenge — not certbot's nginx plugin, which edits a host nginx (ours runs in
  a container). /opt/talentsignal/letsencrypt (certbot writes, nginx mounts read-only)
  and /opt/talentsignal/acme (challenge files). No email registered (nothing personal
  sent to Let's Encrypt; expiry mail ended in 2025; renewal is automatic).
- The web image picks its site config at start (infra/docker/nginx/40-talentsignal-tls.sh):
  no TLS_HOST → http.conf (laptop, CI); TLS_HOST + certificate → https.conf (port 80:
  ACME + 301 to https://<fixed host>; 443: TLS 1.2/1.3 Mozilla intermediate, HTTP/2,
  HSTS max-age 1 day — sslip.io is a borrowed hostname); TLS_HOST, no certificate yet →
  http.conf, which still serves the challenge. TLS_HOST is validated ([a-z0-9.-]).
  infra/docker/test_tls.sh checks both server modes with a self-signed certificate (CI).
- infra/deploy/deploy.sh <sha> (root on the server; flock'd): Parameter Store →
  /opt/talentsignal/.env (600, values single-quoted, never printed) + image refs,
  WEB_BIND=0.0.0.0, TLS_HOST=<EIP with dashes>.sslip.io (from IMDS); compose files and
  update.sh of that commit from GitHub; compose pull + up --wait; first deploy:
  certbot staging dry run, then the real certificate, restart web; systemd units
  talentsignal.service (app at boot), talentsignal-certbot.timer (renew 03:17 / 15:17
  ± 1 h, then nginx reload), talentsignal-update.timer (every 2 min); prune unused
  images; HTTPS health check from the server; then records the commit in DEPLOYED.
- CD = server pulls (D5 revised: OIDC blocked by the Organization's SCP):
  - CI publish job (push to main, after test/dags/ml/api/web/docker; dbt runs on PRs):
    pushes talentsignal-api then talentsignal-web to ghcr.io/ashup1101 as :<sha> and
    :latest (labels: source repo, revision; /version.json in the web image), then checks
    both are pullable anonymously (the server has no GitHub credentials).
  - update.sh on the server: pulls web:latest (the release pointer, pushed last), reads
    its revision label, runs deploy.sh for a new commit; a failed commit is not retried
    (LAST_FAILED) until a newer one arrives — Let's Encrypt limits failed validations.
  - CI release job: waits (≤ 20 min) until https://$APP_HOST/version.json shows the
    commit, then infra/deploy/smoke_test.sh (health, Let's Encrypt certificate,
    http → https 301, HSTS, pages, /api/overview from RDS, the made-up sample resume
    analyzed). Repo variable APP_HOST=77-113-138-96.sslip.io.
- First deploy (bootstraps the timers): infra/deploy/run_remote.sh <instance> <sha>
  over SSM with ts-admin.

Needs from earlier phases:
- Phase 3 marts: skill frequency per role, recent postings with their
  skills, salary by skill.
- Phase 5 salary model: features must all be derivable from a resume
  (target role, skills, seniority, location).

---

## Coding standards
- Type hints on every function signature
- Docstrings on every public function (one-line summary + Args/Returns)
- Environment variables via python-dotenv; keep "Secrets needed" below updated (it is the .env template)
- No hardcoded credentials anywhere — raise ValueError if env var missing
- Logging via Python's logging module (not print statements)
- Tests in tests/ using pytest; at minimum one happy-path test per module

## Secrets needed (set in .env, never committed)
```
RAPIDAPI_KEY=
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_REGION=us-east-1
S3_RAW_BUCKET=talentsignal-raw
S3_PROCESSED_BUCKET=talentsignal-processed
S3_CURATED_BUCKET=talentsignal-curated
RDS_HOST=
RDS_PORT=5432
RDS_DB=talentsignal
RDS_USER=
RDS_PASSWORD=
BLS_CONTACT_EMAIL=          # sent in the User-Agent; BLS blocks anonymous scripts
JSEARCH_MONTHLY_BUDGET=180  # Phase 4: hard cap on JSearch requests per calendar month
JSEARCH_RESERVE_REQUESTS=20 # Phase 4: stop if RapidAPI reports this many or fewer left
DATABRICKS_HOST=            # Phase 5: Databricks Free Edition workspace URL (hosted MLflow)
DATABRICKS_TOKEN=           # Phase 5: personal access token for that workspace
MLFLOW_TRACKING_URI=databricks
MLFLOW_EXPERIMENT_NAME=     # Phase 5: e.g. /Users/<your email>/talentsignal-salary
APP_DB_USER=app_reader     # Phase 6: the app's read-only DB user (src/api/db_setup.py)
APP_DB_PASSWORD=           # Phase 6: random; generated into .env, never printed
```

## What to do if you're blocked
- Missing credential / env var → stop, tell me exactly what's needed
- Unclear schema from API → show me a sample response and ask
- Two valid implementation approaches → list both briefly and ask
- Never invent data, never mock an external call in production code
