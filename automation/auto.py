import csv
import json
from pathlib import Path

import requests


# ------------------------------------------------------------
# CONFIG
# ------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent

INPUT_CSV = BASE_DIR / "input" / "jobs_output_hiring-cafe.csv"

OUTPUT_DIR = BASE_DIR / "output"

CHECKPOINT = OUTPUT_DIR / "checkpoint.json"
OUTPUT_JSON = OUTPUT_DIR / "crl_results.json"
OUTPUT_CSV = OUTPUT_DIR / "crl_results.csv"

API_URL = "http://localhost:3000/roles/generate"
DESCRIPTIONS_URL = "http://localhost:3000/roles"

BATCH_SIZE = 8

MAX_TITLE_LENGTH = 120
MAX_CONTEXT_LENGTH = 6000

ALLOWED_SENIORITY = {"Junior", "Intern"}


# ------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------

def clean_title(value):
    return str(value or "").strip()[:MAX_TITLE_LENGTH]


def clean_context(value):
    return str(value or "").strip()[:MAX_CONTEXT_LENGTH]


def parse_bool(value, default=True):
    if value is None or str(value).strip() == "":
        return default

    return str(value).strip().lower() in {
        "true",
        "1",
        "yes",
        "y"
    }


# ------------------------------------------------------------
# CHECKPOINT
# ------------------------------------------------------------

def save_checkpoint(results):

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    temp_file = CHECKPOINT.with_suffix(".tmp")

    with open(
        temp_file,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            results,
            f,
            indent=2,
            ensure_ascii=False
        )

    temp_file.replace(CHECKPOINT)


def load_checkpoint():

    if not CHECKPOINT.exists():
        return []

    with open(
        CHECKPOINT,
        "r",
        encoding="utf-8"
    ) as f:

        return json.load(f)


# ------------------------------------------------------------
# API
# ------------------------------------------------------------

def generate_role(
    title,
    seniority,
    context,
    include_core,
    overwrite
):

    payload = {
        "title": title,
        "seniority": seniority,
        "context": context,
        "includeCore": include_core,
        "overwrite": overwrite,
    }

    response = requests.post(
        API_URL,
        json=payload,
        timeout=600
    )

    response.raise_for_status()

    return response.json()


def get_descriptions(slug):

    if not slug:
        return []

    response = requests.get(
        f"{DESCRIPTIONS_URL}/{slug}/descriptions",
        timeout=120
    )

    response.raise_for_status()

    data = response.json()

    if isinstance(data, list):
        return data

    return data.get("descriptions", [])


# ------------------------------------------------------------
# FINAL CSV
# ------------------------------------------------------------

def save_final_csv(results):

    rows = []

    for result in results:

        descriptions = result.get(
            "descriptions",
            []
        )

        for description in descriptions:

            if not isinstance(description, dict):
                continue

            row = description.copy()

            row["job_id"] = result.get(
                "job_id",
                ""
            )

            row["input_title"] = result.get(
                "input_title",
                ""
            )

            row["input_seniority"] = result.get(
                "input_seniority",
                ""
            )

            rows.append(row)

    if not rows:
        return

    fields = []

    for row in rows:

        for key in row:

            if key not in fields:
                fields.append(key)

    with open(
        OUTPUT_CSV,
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=fields,
            extrasaction="ignore"
        )

        writer.writeheader()
        writer.writerows(rows)


# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------

def main():

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    if not INPUT_CSV.exists():

        print(
            "Input CSV not found:",
            INPUT_CSV
        )

        return

    # --------------------------------------------------------
    # READ INPUT CSV
    # --------------------------------------------------------

    with open(
        INPUT_CSV,
        "r",
        encoding="cp1252",
        errors="replace",
        newline=""
    ) as f:

        reader = csv.DictReader(f)

        all_rows = list(reader)

    # --------------------------------------------------------
    # FILTER JUNIOR + INTERN
    # --------------------------------------------------------

    rows = [
        row
        for row in all_rows
        if str(
            row.get("seniority") or ""
        ).strip() in ALLOWED_SENIORITY
    ]

    print("=" * 70)
    print("CRL AUTOMATION")
    print("=" * 70)

    print(
        f"Total jobs       : {len(all_rows)}"
    )

    print(
        f"Junior + Intern  : {len(rows)}"
    )

    print(
        f"Batch size       : {BATCH_SIZE}"
    )

    print(
        "Overwrite        : YES"
    )

    print(
        "Fail-fast        : YES"
    )

    print(
        "Retry            : NO"
    )

    print()

    # --------------------------------------------------------
    # LOAD CHECKPOINT
    # --------------------------------------------------------

    results = load_checkpoint()

    completed_ids = {
        str(result.get("job_id"))
        for result in results
        if result.get("job_id")
    }

    remaining = [
        row
        for row in rows
        if str(
            row.get("job_id") or ""
        ) not in completed_ids
    ]

    print(
        f"Already completed : {len(completed_ids)}"
    )

    print(
        f"Remaining         : {len(remaining)}"
    )

    print()

    # --------------------------------------------------------
    # PROCESS BATCHES
    # --------------------------------------------------------

    for batch_start in range(
        0,
        len(remaining),
        BATCH_SIZE
    ):

        batch = remaining[
            batch_start:
            batch_start + BATCH_SIZE
        ]

        batch_number = (
            batch_start // BATCH_SIZE
        ) + 1

        total_batches = (
            len(remaining)
            + BATCH_SIZE
            - 1
        ) // BATCH_SIZE

        print("=" * 70)
        print(
            f"BATCH {batch_number}/{total_batches}"
        )
        print("=" * 70)

        for row in batch:

            job_id = str(
                row.get("job_id") or ""
            ).strip()

            title = clean_title(
                row.get("title")
            )

            seniority = str(
                row.get("seniority") or ""
            ).strip()

            context = clean_context(
                row.get("context")
            )

            include_core = parse_bool(
                row.get("includeCore"),
                True
            )

            # IMPORTANT:
            # Always force regeneration.
            # Do NOT read overwrite from CSV.
            overwrite = True

            print()
            print(
                f"Processing: {title}"
            )
            print(
                f"Job ID: {job_id}"
            )

            try:

                # ------------------------------------------------
                # GENERATE
                # ------------------------------------------------

                result = generate_role(
                    title,
                    seniority,
                    context,
                    include_core,
                    overwrite
                )

                # ------------------------------------------------
                # CHECK RESULT
                # ------------------------------------------------

                slug = result.get("slug")

                descriptions = result.get(
                    "descriptions",
                    []
                )

                if not descriptions and slug:

                    descriptions = get_descriptions(
                        slug
                    )

                # ------------------------------------------------
                # ATTACH METADATA
                # ------------------------------------------------

                result["descriptions"] = descriptions
                result["job_id"] = job_id
                result["input_title"] = title
                result["input_seniority"] = seniority

                # ------------------------------------------------
                # ADD RESULT
                # ------------------------------------------------

                results.append(result)

                # ------------------------------------------------
                # CHECKPOINT
                # ------------------------------------------------

                save_checkpoint(results)

                print(
                    f"✓ Completed "
                    f"({len(descriptions)} CRL rows)"
                )

                print(
                    f"Cached: {result.get('cached')}"
                )

            except Exception as error:

                print()
                print("=" * 70)
                print("FAIL-FAST")
                print("=" * 70)

                print(
                    f"Failed job : {title}"
                )

                print(
                    f"Job ID     : {job_id}"
                )

                print(
                    f"Error      : {error}"
                )

                save_checkpoint(results)

                print()
                print(
                    f"Checkpoint: {CHECKPOINT}"
                )

                print(
                    "Stopping automation."
                )

                return

    # --------------------------------------------------------
    # FINAL JSON
    # --------------------------------------------------------

    with open(
        OUTPUT_JSON,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            results,
            f,
            indent=2,
            ensure_ascii=False
        )

    # --------------------------------------------------------
    # FINAL CSV
    # --------------------------------------------------------

    save_final_csv(results)

    # --------------------------------------------------------
    # DONE
    # --------------------------------------------------------

    print()
    print("=" * 70)
    print("AUTOMATION COMPLETED")
    print("=" * 70)

    print(
        f"Completed jobs : {len(results)}"
    )

    print(
        f"JSON           : {OUTPUT_JSON}"
    )

    print(
        f"CSV            : {OUTPUT_CSV}"
    )

    print(
        f"Checkpoint     : {CHECKPOINT}"
    )


# ------------------------------------------------------------
# ENTRY POINT
# ------------------------------------------------------------

if __name__ == "__main__":
    main()