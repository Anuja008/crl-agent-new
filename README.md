# CRL Role Agent

A NestJS service that takes any job role at runtime, asks the configured LLM to analyse it, and writes role-specific CRL 1–5 descriptions for each of its competencies. Results are saved to a CSV dictionary, so each role is generated once and reused.

## Setup

```bash
npm install
cp .env.example .env      # configure the selected provider's credentials
npm run start:dev
```

Set `LLM_PROVIDER` to `azure`, `gemini`, or `mock`. Provider settings are read when Nest starts; restart the app after changing `.env` so the next request uses the selected provider. `mock` runs with placeholder text and no API key.

For Azure, set `AZURE_OPENAI_ENDPOINT` to the resource endpoint, `AZURE_OPENAI_API_KEY`, and `AZURE_OPENAI_MODEL` to the deployed model's deployment name. Azure requests use the `/openai/v1/chat/completions` endpoint and strict JSON Schema output. The deployed model must support structured outputs. `LLM_TEMPERATURE` controls temperature for Azure and Gemini (default `0.7`).

**Gemini model name:** `GEMINI_MODEL` defaults to `gemini-2.5-flash`.

## API

### Generate a role

```bash
curl -X POST http://localhost:3000/roles/generate \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Cloud Support Associate",
    "seniority": "Fresher",
    "context": "Paste the job posting or employer notes here for more specific output",
    "includeCore": true,
    "overwrite": false
  }'
```

| Field | Required | Default | Meaning |
| --- | --- | --- | --- |
| `title` | Yes | | The job title |
| `seniority` | No | `Fresher` | Changes the scope of each level |
| `context` | No | | Job posting or employer notes. The more real detail, the better the descriptions |
| `includeCore` | No | `true` | Also write role-specific descriptions for the six core competencies |
| `overwrite` | No | `false` | Regenerate a role that already exists |

If the role already exists and `overwrite` is false, the stored rows are returned with `"cached": true` and no model call is made.

### Read stored data

| Endpoint | Returns |
| --- | --- |
| `GET /roles` | All roles in the mapping file |
| `GET /roles/:slug/descriptions` | Stored CRL rows for one role (add `?competency=R05` to filter) |
| `GET /competencies` | The competency dictionary |
| `GET /crl-scale` | The CRL 1–5 scale and rules used in every prompt |

## How the agent works

1. **Analyse the role.** The model receives the full CRL scale, the competency dictionary and the role. It lists the real first-three-months tasks, maps each task to an existing competency, picks 2–6 role competencies, and proposes a new competency only when nothing existing fits.
2. **Resolve.** Competency references are checked against the dictionary. Proposed competencies that duplicate an existing name are reused; genuinely new ones get the next free R-number.
3. **Describe.** For each competency, the model writes CRL 1–5 descriptions using the role's own tasks and tools, with the CRL scale and writing rules in its instructions.
4. **Check and revise.** Every set is checked for vague words, missing level markers (CRL 3 "without being guided", CRL 4 "justifies", CRL 5 "real work"), near-duplicate levels, length, and whether it mentions the role's real tasks. Failures are sent back to the model to rewrite, up to `MAX_REVISIONS` times. If it still fails, it's saved as `Needs review` with the issues listed.
5. **Save.** New competencies go into `competency_dictionary.csv`, the role into `role_competency_mapping.csv`, and descriptions into `role_crl_descriptions.csv`.

## Files in `data/`

| File | Read or written | Contents |
| --- | --- | --- |
| `crl_scale.csv` | Read | The locked CRL 1–5 scale. It goes into every prompt, so editing it changes all future output |
| `competency_dictionary.csv` | Read and appended | All competencies. AI-proposed ones are marked `Candidate (AI-proposed, needs review)` |
| `role_competency_mapping.csv` | Read and upserted | One row per role. Generated roles are marked as hypotheses |
| `role_crl_descriptions.csv` | Written | One row per role × competency × CRL level |

Writes go to a temporary file first and are then renamed, and each file has its own lock, so parallel requests can't corrupt a CSV.

## Project layout

```
src/
  agent/
    prompts.ts             CRL context, system prompts, writing rules
    schemas.ts             Gemini response schemas + Zod validators
    quality.ts             Rule-based checks used in the revise loop
    role-agent.service.ts  The analyse → describe → check → save pipeline
  llm/llm.service.ts       Provider routing: Gemini, Azure OpenAI, JSON validation, retries, mock mode
  dictionary/              Knows the shape of each CSV
  csv/                     Safe CSV reading and writing
  roles/                   REST controller and request validation
```

## Things to know

- **Everything generated is a draft.** Competency mappings and descriptions should be reviewed by a practitioner and confirmed with employer task ratings before being used to rate candidates.
- **Review AI-proposed competencies** before they're used by other roles, to keep the dictionary free of duplicates.
- **The CSV store suits one server instance.** If you run several instances or need many writers, move storage to a database.
- **Cost:** one role with core competencies included is about 10–11 model calls (one analysis plus one per competency), more if revisions are needed.
