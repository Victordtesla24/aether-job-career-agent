# GitHub Repository Analysis: tailor-resume-with-ai

## Scope
Analyzed the public GitHub repository at `https://github.com/Victordtesla24/tailor-resume-with-ai` with focus on:
- Full architecture and folder structure
- Tech stack, frameworks, and languages
- Capabilities and reusable components
- Gaps, limitations, and risks
- API structure and integration points
- Data models and configuration
- Testing, CI/CD, and deployment setup

Repository reviewed locally at: `/home/ubuntu/mini_tasks/inv_0/agent_1/repo`

## Method
Primary methods used:
- Cloned the repository from GitHub
- Read top-level README and environment/config files
- Inspected application entrypoint and core modules under `src/`
- Inspected model-management submodules under `src/models/`
- Reviewed tests and GitHub Actions workflow
- Reviewed project documentation files such as `gaps_analysis.md`, `implementation_guide.md`, and `cline_docs/*`

Important note:
- The repo contains a large `node_modules/` directory, but the actual application is Python-first. The JavaScript package metadata is minimal and appears to support formatting/lint tooling rather than a primary JS app.

## Findings
### 1) Repository purpose and product behavior
The repository implements a Streamlit-based AI resume tailoring application. It is intended to:
- Upload a resume in Word `.docx` format
- Ingest a job description either by pasted text or by scraping a job URL
- Tailor selected resume sections using AI
- Preserve formatting and quantify achievements where possible
- Score ATS alignment and provide improvement suggestions
- Optionally collect anonymized training data

Evidence:
- `README.md` describes “Smart Resume Tailoring App” and lists the main features.
- `app.py` wires together resume upload, job description input, section selection, model selection, and tailoring execution.

### 2) High-level architecture
The architecture is modular and centered around a Streamlit UI that orchestrates service classes in `src/`.

Main layers observed:
- **UI / orchestration:** `app.py`
- **Job ingestion:** `src/job_board.py`
- **ATS scoring / keyword analysis:** `src/ats_scorer.py`, `src/keyword_matcher.py`
- **Model orchestration:** `src/models/model_manager.py`
- **AI client and throughput control:** `src/models/api_client.py`, `src/models/token_bucket.py`, `src/models/batch_processor.py`, `src/models/realtime_handler.py`
- **Formatting preservation:** `src/models/format_handler.py`, `src/formatting.py`, `src/tailoring.py`
- **Prompt and response caching:** `src/models/prompt_cache.py`
- **Training data capture:** `src/models/training_collector.py`, `src/data_collection.py`
- **Configuration and secret management:** `src/config.py`
- **Supporting utilities and additional analysis:** `src/job_recommender.py`, `src/salary_analyzer.py`, `src/realtime_processor.py`, `src/message_handler.py`, etc.

### 3) Full folder structure and notable contents
Top-level structure observed:
- `.github/` — CI workflow, Dependabot, issue/PR templates
- `app.py` — Streamlit entrypoint
- `src/` — core Python application modules
- `tests/` — pytest-based tests
- `static/` — CSS
- `templates/` — HTML templates
- `uploads/` — example generated artifacts and sample input documents
- `cache/` — response cache files
- `training_data/` — training collector output location (created at runtime)
- `cline_docs/` — project context docs
- `requirements.txt`, `pyproject.toml`, `setup.py`, `setup.cfg`, `run.sh`

Key source structure in `src/`:
- `ats_scorer.py`
- `batch_processor.py`
- `cli.py`
- `components.py`
- `config.py`
- `data_collection.py`
- `document_handler.py`
- `exceptions.py`
- `formatting.py`
- `job_board.py`
- `job_recommender.py`
- `keyword_matcher.py`
- `message_handler.py`
- `model_selector.py`
- `models/` package with deeper orchestration components
- `prompt_cache.py`
- `realtime_processor.py`
- `salary_analyzer.py`
- `tailoring.py`
- `training_collector.py`
- `utils.py`

Important artifacts under `uploads/`:
- `Resume.docx`, `Resume.md`
- `Fetched_JD.md`
- `Improved_Resume.md`
- `Tailored_Resume.md`

### 4) Tech stack, languages, and frameworks
Primary stack:
- **Python**: main application language
- **Streamlit**: UI framework (`streamlit==1.40.1`)
- **OpenAI API**: `openai>=1.0.0,<2.0.0`
- **Anthropic API**: `anthropic>=0.3.0,<0.4.0`
- **aiohttp**: async HTTP client for scraping
- **BeautifulSoup4**: HTML parsing
- **python-docx**: Word document parsing
- **spaCy**: NLP (`en_core_web_sm` model is downloaded in setup/CI)
- **scikit-learn**: TF-IDF vectorizer for keyword matching
- **pydantic**: typed data structures / validation support
- **pandas/numpy/thinc**: supporting ML/data dependencies
- **python-dotenv**: env var loading
- **keyring**: secure API key storage in `src/config.py`

Secondary/auxiliary stack:
- **Node tooling**: `package.json` only contains `eslint-config-prettier` and `lint-staged` for prettier formatting; no evidence of a primary JS runtime app.
- **HTML/CSS**: `templates/` and `static/styles.css`
- **GitHub Actions**: CI workflow in `.github/workflows/python-app.yml`

### 5) Capabilities documented in code and README
Observed capabilities include:

#### Resume tailoring workflow
- Upload `.docx` resume and parse it with `python-docx`
- Split resume into sections using header heuristics and fallback AI parsing
- Tailor selected sections: summary, experience, skills, education
- Process sections concurrently via `asyncio`
- Preserve formatting during rewriting
- Highlight metrics and achievements
- Add job-relevant terminology and keywords

#### Job description ingestion
- Accept pasted job description text
- Accept job URL input
- Scrape `seek.com.au` job postings via `aiohttp` + BeautifulSoup
- Extract job title, company, location, and description
- Reject unsupported non-Seek URLs

#### ATS and keyword analysis
- ATS-style score in `src/ats_scorer.py`
- Scoring components:
  - hard skills
  - soft skills
  - experience match
  - education match
  - formatting quality
- Suggest missing skills and formatting fixes
- Keyword extraction with spaCy and TF-IDF support

#### Model and prompt orchestration
- Multi-model support via `ModelManager` and `AVAILABLE_MODELS`
- Prompt templates per model (`gpt-4`, `o1-mini`, `o1-preview` in current config)
- Model selection based on task type, accuracy, cost, and priority
- Response caching to avoid duplicate API usage
- Rate limiting via token bucket
- Batch processing with concurrency controls
- Realtime streaming session support
- Training data collection and validation pipeline

#### Privacy / operational features
- Data anonymization before persistence in `src/data_collection.py`
- Secure key storage through system keyring in `src/config.py`
- Rate limiting and retries around API calls
- Error logging throughout model and scraping flows

#### Additional domain features
- Job recommender and salary analyzer modules exist, but their source was not fully read in this pass, so detailed behavior is only partially verified.

### 6) Reusable components and module responsibilities
Key reusable components are clearly separated:

- `ModelManager`: main orchestrator for tailoring, section detection, model selection, caching, metrics, and training-data collection
- `APIClient`: reusable async OpenAI client with retries, streaming, metrics, and token-bucket gating
- `BatchProcessor`: reusable batch executor with cost estimation and concurrency limit
- `ModelSelector`: model ranking and fallback logic
- `PromptCache`: file/memory cache for prompt-response pairs
- `RealtimeHandler`: session wrapper around streaming model responses
- `TokenBucket`: rate limiter reusable across API calls
- `FormatHandler` / `FormatPreserver` / `MarkdownFormatter`: formatting and normalization helpers
- `SkillAnalyzer`: skill-level estimation and industry terminology checks
- `DataCollector` / `TrainingCollector`: anonymized data logging and validation pipeline
- `JobBoardClient`: source-specific job extraction client (Seek-only)

### 7) API structure and execution flow
No web server API endpoints were found. The primary application interface is the Streamlit app in `app.py`, and the “API structure” is internal/service-oriented rather than HTTP-route-based.

Observed internal call flow:
1. `app.py` starts Streamlit UI
2. User uploads resume and supplies job description or URL
3. If URL is provided, `JobBoardClient.fetch_job_description()` fetches and parses Seek HTML
4. `ModelManager._determine_sections()` splits resume into sections
5. For each selected section, `process_section()` builds a prompt and calls `ModelManager.get_completion()`
6. `ModelManager.validate_output()` checks length, keyword retention, and job alignment
7. Tailored sections are reassembled and shown to the user

Internal APIs / methods worth noting:
- `ModelManager.generate_tailored_resume(...)`
- `ModelManager.get_prompt(...)`
- `ModelManager.get_completion(...)`
- `ModelManager.validate_output(...)`
- `JobBoardClient.fetch_job_description(url)`
- `ATSScorer.calculate_score(resume_text, job_description)`
- `DataCollector.save_training_data(...)`
- `TrainingCollector.collect_interaction(...)`
- `RealtimeHandler.start_session(...)`, `send_message(...)`, `get_response(...)`

### 8) Data models and structured types
The repo uses a mix of dataclasses, TypedDicts, and plain dictionaries.

Observed structured types:
- `src/models/types.py`
  - `ModelConfig`
  - `PerformanceMetrics`
  - `SkillMetrics`
  - `ResponseQueue`
  - `FormatPattern` (`TypedDict`)
- `src/models/config.py`
  - `APIConfig` dataclass
- `src/models/model_selector.py`
  - `ModelPerformance` dataclass
  - `TaskPriority` enum
- `src/models/training_collector.py`
  - `TrainingExample` dataclass
- `src/formatting.py`
  - `SectionFormat` dataclass
- `src/keyword_matcher.py`
  - TypedDicts for validation and scoring results

Persistent data formats observed:
- Prompt cache: JSON files in `cache/model_responses/*.json`
- Training batches: JSONL in `training_data/`
- Training examples: per-example JSON files in `training_data/`
- Template effectiveness stats: `template_stats.json`
- Uploaded/generated resume/job artifacts in `uploads/`

### 9) Configuration and secret management
Configuration sources:
- `.env.example` documents expected env vars:
  - `OPENAI_API_KEY`
  - `ANTHROPIC_API_KEY`
  - `DEFAULT_MODEL`
  - `FALLBACK_MODEL`
  - `MAX_TOKENS`
  - `TEMPERATURE`
  - `ENABLE_DATA_COLLECTION`
- `src/config.py` loads/stores API keys in system keyring and applies rate limiting
- `src/models/config.py` loads model definitions from `AVAILABLE_MODELS` env var if present, otherwise defaults to embedded JSON config
- `README.md` mentions a `config.json` file for rate limits, but no root `config.json` was present in the inspected tree

Security-related config behavior:
- API keys can be stored in keyring rather than plaintext config
- `DataCollector` writes anonymized output to a secure storage path returned by `get_secure_storage_path()`

### 10) Testing and quality gates
Testing present:
- `tests/` contains:
  - `test_data_collection.py`
  - `test_formatting.py`
  - `test_job_board.py`
  - `test_keyword_matcher.py`
  - `test_models.py`
  - `conftest.py`

Observed CI/test setup:
- GitHub Actions workflow exists at `.github/workflows/python-app.yml`
- Workflow installs dependencies and spaCy model
- Test execution is commented out in CI (`# - name: Run tests`)

Additional developer tooling:
- `setup.cfg`, `.flake8`, `.pre-commit-config.yaml`, `.prettierrc`, `.markdownlint.json`
- README documents `pytest`, `mypy src tests`, `flake8 src tests`, and coverage command

Important limitation:
- Tests exist, but CI does not currently execute them automatically because the run step is disabled.

### 11) Deployment and runtime setup
Deployment/runtime observations:
- Primary runtime command in README: `streamlit run app.py`
- `run.sh` exists, but was not read in this pass; its exact deployment contents are therefore not verified here
- GitHub Actions builds on Ubuntu with Python 3.11, installs deps, and downloads spaCy model
- No Dockerfile was found in the inspected tree
- No cloud deployment manifests (e.g., Kubernetes, Terraform, Procfile, Render, Heroku, Fly, etc.) were observed in the reviewed files

### 12) Extensibility and integration points
Strong extension points identified:
- `AVAILABLE_MODELS` is dynamically loaded from environment variable `AVAILABLE_MODELS` in `src/models/config.py`
- `ModelSelector` can adapt model choice using performance history, cost, and task type
- `PromptCache` and `TrainingCollector` create feedback loops for future optimization
- `JobBoardClient` can be extended to support additional job boards beyond Seek
- `SectionTailor` and formatting helpers can be extended for more resume sections or output formats
- `DataCollector` is already structured to accept section-specific quality metrics and template IDs
- `RealtimeHandler` and streaming response handling can support interactive workflows

Integration points with external systems:
- OpenAI Chat Completions API
- Anthropic API is declared in dependencies and environment config, but I did not find a fully verified Anthropic client implementation in the inspected code path
- Seek.com.au HTML structure via scraping selectors
- System keyring for secrets
- spaCy language model download at install time / CI time

### 13) Gaps, limitations, and risks
Verified limitations:
- **Seek-only scraping**: `JobBoardClient` explicitly rejects non-`seek.com.au` URLs.
- **No HTTP backend API**: the app is Streamlit-first; no FastAPI/Flask route layer exists in the reviewed code.
- **Testing disabled in CI**: workflow comments out the test step.
- **Potential code path inconsistencies**: `app.py` imports `from src.models import ModelManager`, but several root-level modules and subpackage modules overlap in naming and responsibility, suggesting legacy/migrated code paths.
- **Formatting preservation is heuristic**: multiple format handlers rely on regex and simple line transforms, which may break complex DOCX layouts.
- **Resume section detection is heuristic**: relies on section headers and fallback AI parsing; uncommon resume formats may fail.
- **Job extraction is brittle**: depends on Seek DOM attributes like `data-automation="job-detail-title"` and similar selectors.
- **Anthropic support is advertised, but not fully evidenced in the inspected core execution flow**.
- **Some documentation may be stale**: README references a `models.py` and `config.json` pattern not fully aligned with the current `src/models/` package layout.

Potential quality concerns in code observed directly:
- `app.py` uses `batch_items[0]` when collecting training data inside the loop, which may attach the wrong prompt/model metadata to later sections.
- `FormatHandler._apply_format_pattern()` joins lines with spaces after processing, which can collapse intended line structure.
- `DataCollector.anonymize_text()` includes a broad name-matching regex that may over-redact legitimate content.
- CI does not validate tests, so regressions can slip through.

## Evidence / Metrics
Concrete evidence observed:
- Python app entrypoint: `app.py`
- Streamlit version pinned: `streamlit==1.40.1` in `requirements.txt`
- OpenAI dependency: `openai>=1.0.0,<2.0.0`
- Anthropic dependency: `anthropic>=0.3.0,<0.4.0`
- spaCy dependency: `spacy>=3.3.0`; model download in CI via `python -m spacy download en_core_web_sm`
- Tests present: 5 test modules in `tests/`
- CI workflow present: `.github/workflows/python-app.yml`
- Test step in CI is commented out
- Prompt cache TTL: 24 hours (`PromptCache.max_age = timedelta(hours=24)`)
- Training collector batch size: 100 examples per batch
- API rate limiting defaults in `src/config.py`: 100 requests / 3600 seconds for OpenAI and Anthropic, translated into per-minute token bucket rate
- Model config contains three default models: `gpt-4`, `o1-mini`, `o1-preview`
- Resume tailoring UI supports 4 sections: summary, experience, skills, education
- Job board support is limited to Seek (`seek.com.au`)

## Technologies
- Python 3.x
- Streamlit
- OpenAI SDK
- Anthropic SDK
- aiohttp
- BeautifulSoup4
- python-docx
- python-dotenv
- spaCy
- scikit-learn
- pydantic
- numpy
- pandas
- keyring
- pytest (documented; tests directory present)
- GitHub Actions
- ESLint/Prettier-related Node tooling for formatting support only

## Structure / Architecture
### Runtime architecture
- **Presentation layer:** Streamlit page built in `app.py`
- **Domain services:** job scraping, ATS scoring, tailoring heuristics, analytics, model orchestration
- **Infrastructure layer:** API client, token bucket, cache, keyring, training-data persistence
- **Support layer:** formatting helpers, keyword extraction, utility functions, docs, and tests

### Data flow
1. Resume `.docx` is uploaded
2. Resume is read and split into section text
3. Job description comes from text input or Seek scraping
4. ModelManager generates prompts per selected section
5. APIClient calls the chosen model with retries and token limiting
6. Responses are validated and formatted
7. Tailored output is displayed; optional training data may be saved

### Folder-by-folder summary
- `src/`: core app logic and reusable services
- `src/models/`: model orchestration, selection, batch processing, caching, streaming, and training capture
- `tests/`: unit tests for core components
- `.github/`: CI and contribution automation
- `static/`: styling
- `templates/`: HTML templates
- `uploads/`: sample artifacts / outputs
- `cache/`: runtime prompt-response cache
- `cline_docs/`: project context documentation

## Opportunities / Gaps
### Verified gaps
- No authenticated user/accounts layer
- No database-backed persistence layer observed
- No REST/GraphQL API exposed
- No containerization or deployment manifest found
- CI does not run tests
- Only one job board source is supported
- Resume input is limited to `.docx`
- No explicit PDF resume handling found in the reviewed flow

### Recommended opportunities
- Add robust parsing for PDF and multi-format resumes
- Add more job boards and structured job-source adapters
- Replace heuristic section detection with a more reliable parser or LLM-assisted structured extraction
- Re-enable CI tests and add coverage thresholds
- Add Docker and deployment manifests for reproducible environments
- Introduce end-to-end tests around the Streamlit workflow
- Separate legacy and current code paths to reduce overlap and confusion
- Add a documented public API if integration by other systems is intended
- Improve training-data schema versioning and persistence isolation

## Notes
- Some repository docs appear to reference older structure (`models.py` in README) while the current code uses a richer `src/models/` package. I treated the code as the source of truth where conflicts existed.
- `node_modules/` is present in the cloned repository and significantly increases tree size, but it does not appear to be the core application runtime.
- `src/job_recommender.py`, `src/salary_analyzer.py`, `src/document_handler.py`, `src/components.py`, `src/message_handler.py`, and `run.sh` were discovered but not fully read in this pass; therefore their behavior is only partially inferred from imports/naming, not fully verified.
- If a claim could not be directly verified from code or docs, it was omitted or explicitly marked as unverified.
