import csv
import json
import os
import random
import platform
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
BATCH_PAUSE_SECONDS = 0.5
REQUEST_TIMEOUT = 600
REQUEST_RETRIES = 4
REQUEST_BACKOFF_SECONDS = 2
REQUEST_JITTER_SECONDS = 0.75
DEFAULT_WORKERS = int(os.getenv("AUTO_WORKERS", "6" if platform.system() == "Darwin" else "4"))

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


def retry_sleep(attempt):
    base = REQUEST_BACKOFF_SECONDS * (2 ** max(0, attempt - 1))
    jitter = random.uniform(0, REQUEST_JITTER_SECONDS)
    time.sleep(base + jitter)


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


def request_json(
    session,
    method,
    url,
    *,
    json_body=None,
    timeout=REQUEST_TIMEOUT,
    retries=REQUEST_RETRIES
):

    last_error = None

    for attempt in range(1, retries + 1):

        try:

            response = session.request(
                method,
                url,
                json=json_body,
                timeout=timeout
            )

            if response.ok:
                return response.json()

            body = response.text.strip()
            snippet = body[:500] if body else response.reason
            error = requests.HTTPError(
                f"{method} {url} failed with {response.status_code}: {snippet}",
                response=response,
            )

            if response.status_code not in {429, 500, 502, 503, 504}:
                raise error

            last_error = error

        except (requests.RequestException, ValueError) as error:
            response = getattr(error, "response", None)
            status_code = getattr(response, "status_code", None)

            if isinstance(error, requests.HTTPError) and status_code not in {429, 500, 502, 503, 504}:
                raise

            last_error = error

        if attempt < retries:
            retry_sleep(attempt)

    if last_error:
        raise last_error

    raise RuntimeError(f"{method} {url} failed")


def build_csv_rows(results):

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

    return rows


def write_csv_rows(rows, mode="w"):

    if not rows:
        return

    fields = []

    for row in rows:

        for key in row:

            if key not in fields:
                fields.append(key)

    if mode == "a":

        file_exists = OUTPUT_CSV.exists()

        with open(
            OUTPUT_CSV,
            "a",
            newline="",
            encoding="utf-8-sig"
        ) as f:

            writer = csv.DictWriter(
                f,
                fieldnames=fields,
                extrasaction="ignore"
            )

            if not file_exists or OUTPUT_CSV.stat().st_size == 0:
                writer.writeheader()

            writer.writerows(rows)
            f.flush()
            os.fsync(f.fileno())

        return

    temp_file = OUTPUT_CSV.with_suffix(".tmp")

    with open(
        temp_file,
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
        f.flush()
        os.fsync(f.fileno())

    temp_file.replace(OUTPUT_CSV)


def save_csv(results):

    write_csv_rows(build_csv_rows(results), mode="w")


def append_csv_result(result):

    write_csv_rows(build_csv_rows([result]), mode="a")


# ------------------------------------------------------------
# API
# ------------------------------------------------------------

def generate_role(
    session,
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

    response = request_json(
        session,
        "POST",
        API_URL,
        json_body=payload
    )

    return response


def get_descriptions(session, slug):

    if not slug:
        return []

    data = request_json(
        session,
        "GET",
        f"{DESCRIPTIONS_URL}/{slug}/descriptions",
        timeout=120,
    )

    if isinstance(data, list):
        return data

    return data.get("descriptions", [])


def process_row(row):

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

    with requests.Session() as session:

        result = generate_role(
            session,
            title,
            seniority,
            context,
            include_core,
            overwrite
        )

        slug = result.get("slug")
        descriptions = result.get("descriptions", [])

        if not descriptions and slug:
            descriptions = get_descriptions(session, slug)

        result["descriptions"] = descriptions
        result["job_id"] = job_id
        result["input_title"] = title
        result["input_seniority"] = seniority

        return result


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
        f"Batch pause      : {BATCH_PAUSE_SECONDS}s"
    )

    print(
        f"Workers          : {DEFAULT_WORKERS}"
    )

    print(
        "Overwrite        : YES"
    )

    print(
        "Fail-fast        : YES"
    )

    print(
        "Retry            : YES (with jitter)"
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

        if batch_start:
            time.sleep(BATCH_PAUSE_SECONDS)

        worker_count = min(DEFAULT_WORKERS, BATCH_SIZE, len(batch))
        executor = ThreadPoolExecutor(max_workers=worker_count)
        stop_early = False

        try:

            futures = {}

            for row in batch:
                job_id = str(row.get("job_id") or "").strip()
                title = clean_title(row.get("title"))

                print()
                print(f"Processing: {title}")
                print(f"Job ID: {job_id}")

                future = executor.submit(process_row, row)
                futures[future] = {
                    "job_id": job_id,
                    "title": title,
                }

            for future in as_completed(futures):
                meta = futures[future]

                try:
                    result = future.result()

                    descriptions = result.get(
                        "descriptions",
                        []
                    )

                    results.append(result)

                    save_checkpoint(results)
                    append_csv_result(result)

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
                        f"Failed job : {meta['title']}"
                    )

                    print(
                        f"Job ID     : {meta['job_id']}"
                    )

                    print(
                        f"Error      : {error}"
                    )

                    save_checkpoint(results)
                    save_csv(results)

                    for pending in futures:
                        if pending is not future:
                            pending.cancel()

                    executor.shutdown(wait=False, cancel_futures=True)

                    print()
                    print(
                        f"Checkpoint: {CHECKPOINT}"
                    )

                    print(
                        "Stopping automation."
                    )

                    stop_early = True
                    break

        finally:
            if not stop_early:
                executor.shutdown(wait=True, cancel_futures=False)

        if stop_early:
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

    save_csv(results)

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
