"""The skill dictionary shared by job postings and resumes (no Spark needed).

src/processing/extract_skills.py applies it to postings inside a Spark pandas
UDF; src/ml/resume_features.py (and the Phase 6 app) apply it to resume text.
One set of patterns means a skill is recognised the same way everywhere.
"""

from __future__ import annotations

import re
from functools import lru_cache

# canonical name -> (category, aliases). Aliases match case-insensitively on word
# boundaries unless the skill is listed in CASE_SENSITIVE.
SKILLS: dict[str, tuple[str, tuple[str, ...]]] = {
    # Languages
    "Python": ("language", ("Python",)),
    "SQL": ("language", ("SQL",)),
    "Java": ("language", ("Java",)),
    "Scala": ("language", ("Scala",)),
    "R": ("language", ()),  # CUSTOM_PATTERNS
    "Go": ("language", ()),  # CUSTOM_PATTERNS
    "Rust": ("language", ("Rust",)),
    "C++": ("language", ("C++",)),
    "C#": ("language", ("C#",)),
    "JavaScript": ("language", ("JavaScript",)),
    "TypeScript": ("language", ("TypeScript",)),
    "Bash": ("language", ("Bash", "shell scripting")),
    "Kotlin": ("language", ("Kotlin",)),
    "Ruby": ("language", ("Ruby",)),
    "PHP": ("language", ("PHP",)),
    "MATLAB": ("language", ("MATLAB",)),
    "SAS": ("language", ("SAS",)),
    # Data engineering
    "Spark": ("data_engineering", ("Spark", "PySpark", "Spark SQL")),
    "Hadoop": ("data_engineering", ("Hadoop", "HDFS")),
    "Kafka": ("data_engineering", ("Kafka",)),
    "Flink": ("data_engineering", ("Flink",)),
    "Airflow": ("data_engineering", ("Airflow",)),
    "dbt": ("data_engineering", ("dbt",)),
    "Databricks": ("data_engineering", ("Databricks",)),
    "Snowflake": ("data_engineering", ("Snowflake",)),
    "BigQuery": ("data_engineering", ("BigQuery",)),
    "Redshift": ("data_engineering", ("Redshift",)),
    "Hive": ("data_engineering", ("Hive",)),
    "Presto/Trino": ("data_engineering", ("Presto", "Trino")),
    "Delta Lake": ("data_engineering", ("Delta Lake",)),
    "Iceberg": ("data_engineering", ("Apache Iceberg", "Iceberg")),
    "Apache Beam": ("data_engineering", ("Apache Beam",)),
    "NiFi": ("data_engineering", ("NiFi",)),
    "Informatica": ("data_engineering", ("Informatica",)),
    "Fivetran": ("data_engineering", ("Fivetran",)),
    "SSIS": ("data_engineering", ("SSIS",)),
    "Talend": ("data_engineering", ("Talend",)),
    "AWS Glue": ("data_engineering", ("AWS Glue", "Glue jobs", "Glue ETL")),
    "EMR": ("data_engineering", ("EMR",)),
    "Kinesis": ("data_engineering", ("Kinesis",)),
    "Azure Data Factory": ("data_engineering", ("Azure Data Factory", "ADF")),
    "Azure Synapse": ("data_engineering", ("Synapse",)),
    "ETL": ("data_engineering", ("ETL", "ELT")),
    "Data Modeling": ("data_engineering", ("data modeling", "data modelling", "dimensional modeling")),
    "Data Warehousing": ("data_engineering", ("data warehouse", "data warehousing", "data lakehouse")),
    # Databases
    "PostgreSQL": ("database", ("PostgreSQL", "Postgres")),
    "MySQL": ("database", ("MySQL",)),
    "SQL Server": ("database", ("SQL Server", "MSSQL", "T-SQL")),
    "Oracle": ("database", ("Oracle",)),
    "MongoDB": ("database", ("MongoDB", "Mongo")),
    "Cassandra": ("database", ("Cassandra",)),
    "DynamoDB": ("database", ("DynamoDB",)),
    "Redis": ("database", ("Redis",)),
    "Elasticsearch": ("database", ("Elasticsearch", "Elastic Search", "OpenSearch")),
    "Neo4j": ("database", ("Neo4j",)),
    "NoSQL": ("database", ("NoSQL",)),
    # Cloud
    "AWS": ("cloud", ("AWS", "Amazon Web Services")),
    "Azure": ("cloud", ("Azure",)),
    "GCP": ("cloud", ("GCP", "Google Cloud")),
    "S3": ("cloud", ("S3",)),
    "AWS Lambda": ("cloud", ("AWS Lambda", "Lambda functions")),
    "EC2": ("cloud", ("EC2",)),
    # DevOps
    "Docker": ("devops", ("Docker",)),
    "Kubernetes": ("devops", ("Kubernetes", "K8s", "EKS", "AKS", "GKE")),
    "Terraform": ("devops", ("Terraform",)),
    "Git": ("devops", ("Git",)),
    "GitHub Actions": ("devops", ("GitHub Actions",)),
    "Jenkins": ("devops", ("Jenkins",)),
    "CI/CD": ("devops", ("CI/CD", "CICD", "continuous integration")),
    "Linux": ("devops", ("Linux", "Unix")),
    # ML / AI
    "Machine Learning": ("ml_ai", ("machine learning", "ML")),
    "Deep Learning": ("ml_ai", ("deep learning", "neural network", "neural networks")),
    "PyTorch": ("ml_ai", ("PyTorch",)),
    "TensorFlow": ("ml_ai", ("TensorFlow",)),
    "Keras": ("ml_ai", ("Keras",)),
    "scikit-learn": ("ml_ai", ("scikit-learn", "sklearn", "scikit learn")),
    "XGBoost": ("ml_ai", ("XGBoost", "LightGBM", "gradient boosting")),
    "Pandas": ("ml_ai", ("Pandas",)),
    "NumPy": ("ml_ai", ("NumPy",)),
    "NLP": ("ml_ai", ("NLP", "natural language processing")),
    "Computer Vision": ("ml_ai", ("computer vision",)),
    "LLMs": ("ml_ai", ("LLM", "LLMs", "large language model", "large language models")),
    "Generative AI": ("ml_ai", ("generative AI", "GenAI", "Gen AI")),
    "RAG": ("ml_ai", ("RAG", "retrieval-augmented generation", "retrieval augmented generation")),
    "Hugging Face": ("ml_ai", ("Hugging Face", "HuggingFace")),
    "LangChain": ("ml_ai", ("LangChain",)),
    "MLflow": ("ml_ai", ("MLflow",)),
    "SageMaker": ("ml_ai", ("SageMaker",)),
    "Vertex AI": ("ml_ai", ("Vertex AI",)),
    "MLOps": ("ml_ai", ("MLOps",)),
    "Statistics": ("ml_ai", ("statistics", "statistical")),
    "A/B Testing": ("ml_ai", ("A/B test", "A/B tests", "A/B testing", "AB testing")),
    # Not plain "forecasting": in analyst postings that usually means business planning.
    "Time Series": ("ml_ai", ("time series", "time-series", "ARIMA", "forecasting models")),
    "Reinforcement Learning": ("ml_ai", ("reinforcement learning",)),
    # Analytics / BI
    "Tableau": ("analytics_bi", ("Tableau",)),
    "Power BI": ("analytics_bi", ("Power BI", "PowerBI")),
    "Looker": ("analytics_bi", ("Looker",)),
    "Excel": ("analytics_bi", ("Excel",)),
    "Qlik": ("analytics_bi", ("Qlik",)),
    "Superset": ("analytics_bi", ("Superset",)),
    "Alteryx": ("analytics_bi", ("Alteryx",)),
    # Web / backend
    "React": ("web", ("React", "React.js", "ReactJS")),
    "Node.js": ("web", ("Node.js", "NodeJS")),
    "Django": ("web", ("Django",)),
    "Flask": ("web", ("Flask",)),
    "FastAPI": ("web", ("FastAPI",)),
    "Spring": ("web", ("Spring Boot", "Spring Framework")),
    "GraphQL": ("web", ("GraphQL",)),
    "REST APIs": ("web", ("REST API", "REST APIs", "RESTful")),
    "Microservices": ("web", ("microservices", "microservice")),
}

# Also ordinary English words or short acronyms, so only exact capitalization counts
# ("React" vs "react quickly", "Excel" vs "excel at", "Snowflake" vs "snowflake schema").
CASE_SENSITIVE = {
    "AWS", "EMR", "Azure Data Factory", "Excel", "Hive", "Iceberg", "Oracle", "RAG", "React",
    "SAS", "S3", "Snowflake", "Spring", "Superset",
}

# Names too ambiguous for plain alias matching.
CUSTOM_PATTERNS = {
    # "Go": only as golang or inside a list ("Python, Go, Rust" / "Go/Java"), never "Go above and beyond".
    "Go": r"(?i:\bgolang\b)|(?<=[,/(] )Go\b|(?<=[,/(])Go\b|\bGo(?=\s*[,/)])",
    # "R": standalone capital R, not "R&D", "R-squared" or "R2".
    "R": r"(?<![A-Za-z0-9&/-])R(?![A-Za-z0-9&+#'-])",
}

# Alias boundaries: not glued to other letters/digits, and "+"/"#" so "C" never matches "C++"/"C#".
_LEFT = r"(?<![A-Za-z0-9+#])"
_RIGHT = r"(?![A-Za-z0-9+#])"


def skill_patterns() -> dict[str, re.Pattern[str]]:
    """Compile one regex per canonical skill from SKILLS, CASE_SENSITIVE and CUSTOM_PATTERNS.

    Returns:
        Mapping of canonical skill name to its compiled pattern.
    """
    patterns: dict[str, re.Pattern[str]] = {}
    for name, (_, aliases) in SKILLS.items():
        if name in CUSTOM_PATTERNS:
            patterns[name] = re.compile(CUSTOM_PATTERNS[name])
            continue
        alternation = "|".join(re.escape(a) for a in sorted(aliases, key=len, reverse=True))
        flags = 0 if name in CASE_SENSITIVE else re.IGNORECASE
        patterns[name] = re.compile(f"{_LEFT}(?:{alternation}){_RIGHT}", flags)
    return patterns


@lru_cache(maxsize=1)
def _compiled_patterns() -> tuple[tuple[str, re.Pattern[str]], ...]:
    # Compile the ~110 patterns once per process (the app parses many resumes).
    return tuple(skill_patterns().items())


def find_skills(text: str | None) -> list[str]:
    """Return the canonical names of the dictionary skills mentioned in a text.

    Args:
        text: Any text, e.g. a posting's title + description or a resume.
            None or a non-string yields no skills.

    Returns:
        Skill names in SKILLS order, each at most once.
    """
    if not isinstance(text, str):
        return []
    return [name for name, rx in _compiled_patterns() if rx.search(text)]
