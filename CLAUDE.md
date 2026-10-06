# TalentSignal — Project Specification for Claude Code

## What this is
An end-to-end job market intelligence platform. Raw job postings are ingested
from public APIs, processed at scale with PySpark on Databricks, modeled with
dbt, orchestrated by Airflow, enriched with NLP + ML, and served through a
hosted Streamlit app on AWS EC2.

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
- App: four-page Streamlit resume intelligence tool on EC2 behind nginx,
  CI/CD via GitHub Actions. Upload a resume PDF → skills found (regex +
  keyword matching with the pipeline's skill dictionary, no LLM) with their
  demand in real postings, match % per target role, XGBoost salary
  prediction, top 3 missing skills with estimated salary impact, and this
  week's matching postings.

Numbers above are targets, not facts. Measure them on real data and report
the actual result (e.g. real held-out MAE), even if it misses the target.

---

## Tech stack (use exactly these, no substitutions without asking)
- Ingestion:        Python 3.11, boto3, requests, JSearch API (RapidAPI)
- Storage:          AWS S3 (raw / processed / curated zones), AWS RDS PostgreSQL
- Processing:       PySpark, Databricks (Delta Lake format)
- Transformation:   dbt Core (dbt-postgres adapter)
- Orchestration:    Apache Airflow 2.x (Docker Compose locally)
- NLP:              spaCy, sentence-transformers, BERTopic, VADER
- ML:               XGBoost, Prophet, scikit-learn, MLflow (Databricks-hosted)
- App:              Streamlit, pdfplumber (resume PDF → text)
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
│   └── docker-compose.yml        # Airflow local dev
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
│   │   └── load_postgres.py      # Delta tables → RDS raw schema (JDBC)
│   │
│   ├── dbt_project/              # full dbt project lives here
│   │   ├── dbt_project.yml
│   │   ├── profiles.yml.example
│   │   ├── models/
│   │   │   ├── sources.yml       # raw.* tables loaded by load_postgres.py
│   │   │   ├── staging/
│   │   │   │   ├── stg_jobs.sql
│   │   │   │   ├── stg_skills.sql
│   │   │   │   └── stg_bls_occupations.sql
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
│   │   │       └── mart_skill_salary.sql
│   │   ├── seeds/
│   │   │   └── role_soc_mapping.csv
│   │   └── tests/
│   │
│   ├── dags/                     # Airflow DAGs
│   │   └── talentsignal_pipeline.py
│   │
│   ├── ml/
│   │   ├── nlp_pipeline.py       # spaCy + BERTopic skill extraction + clustering
│   │   ├── salary_model.py       # XGBoost regressor + MLflow logging
│   │   └── demand_forecast.py    # Prophet time-series per skill
│   │
│   └── app/
│       ├── streamlit_app.py      # entry point
│       └── pages/                # Streamlit orders the sidebar by filename
│           ├── 01_resume_analyzer.py  # upload resume PDF → skills, match %, salary, gaps
│           ├── 02_salary_explorer.py
│           ├── 03_skill_demand.py     # Skill Demand Forecast (Prophet)
│           └── 04_job_insights.py
│
├── tests/
│   ├── test_ingestion.py
│   ├── test_processing.py        # local SparkSession, no S3/Delta
│   └── test_ml.py
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

### Phase 4 — Airflow orchestration
Build after Phase 3 is confirmed working.
Details: TBD — ask for spec when Phase 3 is done.

### Phase 5 — NLP + ML models
Build after Phase 4 is confirmed working.
Details: TBD — ask for spec when Phase 4 is done.

### Phase 6 — Streamlit app + EC2 hosting
Build after Phase 5 is confirmed working. Hosting details (EC2, nginx,
systemd, deploy): ask for spec when Phase 5 is done.

App direction (set 2026-10-04): a resume intelligence tool, not a generic
market dashboard.

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
- Skill dictionary shared without Spark: move SKILLS / CASE_SENSITIVE /
  CUSTOM_PATTERNS / skill_patterns() into a Spark-free module imported by
  both extract_skills.py and the app (the app server has no PySpark/Java).
- Resumes are personal data: parse in memory only; never write uploads or
  their text to disk, S3 or logs.
- Text-based PDFs only (no OCR); a scanned/image-only PDF yields no text →
  show a clear message instead of an empty analysis.

Open questions (decide before building):
- Match % formula (e.g. demand-weighted share of a role's top skills found).
- Salary impact of a missing skill: model what-if vs. median salary of
  postings with vs. without the skill. Both are associations, not causal —
  UI wording must say "associated with".
- "This week's postings" needs ingestion at least weekly; the JSearch free
  plan (200 requests/month) limits how many postings that covers.

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
```

## What to do if you're blocked
- Missing credential / env var → stop, tell me exactly what's needed
- Unclear schema from API → show me a sample response and ask
- Two valid implementation approaches → list both briefly and ask
- Never invent data, never mock an external call in production code
