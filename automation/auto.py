import csv
import json
import os
import requests

API_URL = "http://localhost:3000"

INPUT_CSV = "../input/ jobs_output_hiring-cafe.csv"
OUTPUT_JSON = "../output/crl_results.json"
OUTPUT_CSV = "../output/crl_results.csv"

ALLOWED_SENIORITY = {"Junior", "Intern"}

# Keep the context reasonably sized for the CRL agent
MAX_CONTEXT_LENGTH = 6000


def clean_context(context):
    context = context.strip()

    if len(context) > MAX_CONTEXT_LENGTH:
        context = context[:MAX_CONTEXT_LENGTH]

    return context


def generate_role(row):

    payload = {
        "title": row["title"].strip(),
        "seniority": row["seniority"].strip(),
        "context": clean_context(row["context"]),
        "includeCore": row["includeCore"].strip().lower() == "true",
        "overwrite": row["overwrite"].strip().lower() == "true"
    }

    response = requests.post(
        f"{API_URL}/roles/generate",
        json=payload,
        timeout=600
    )

    if not response.ok:
        print("\n    API ERROR:")
        print(f"    Status: {response.status_code}")
        print(f"    Response: {response.text[:2000]}\n")

    response.raise_for_status()

    return response.json()


def get_descriptions(slug):

    response = requests.get(
        f"{API_URL}/roles/{slug}/descriptions",
        timeout=120
    )

    response.raise_for_status()

    data = response.json()

    if isinstance(data, list):
        return data

    return data.get("descriptions", [])


def main():

    os.makedirs("../output", exist_ok=True)

    results = []
    all_descriptions = []

    with open(
        INPUT_CSV,
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as file:

        reader = csv.DictReader(file)

        rows = [
            row
            for row in reader
            if row["seniority"].strip() in ALLOWED_SENIORITY
        ]

    print(f"Total Junior/Intern roles: {len(rows)}")

    for index, row in enumerate(rows, 1):

        title = row["title"].strip()
        seniority = row["seniority"].strip()

        print(
            f"\n[{index}/{len(rows)}] "
            f"{seniority} - {title}"
        )

        try:

            result = generate_role(row)

            slug = result.get("slug")

            descriptions = result.get(
                "descriptions",
                []
            )

            if not descriptions and slug:

                print(
                    "    Fetching CRL descriptions..."
                )

                descriptions = get_descriptions(slug)

            result["descriptions"] = descriptions

            results.append(result)

            all_descriptions.extend(
                descriptions
            )

            print(
                f"    ✓ {len(descriptions)} CRL rows"
            )

        except Exception as e:

            print(
                f"    ✗ Failed: {e}"
            )

            results.append({
                "job_id": row["job_id"],
                "title": title,
                "seniority": seniority,
                "error": str(e)
            })

    # Save JSON
    with open(
        OUTPUT_JSON,
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            results,
            file,
            indent=2,
            ensure_ascii=False
        )

    # Save CSV
    if all_descriptions:

        fields = []

        for row in all_descriptions:

            for key in row:

                if key not in fields:
                    fields.append(key)

        with open(
            OUTPUT_CSV,
            "w",
            newline="",
            encoding="utf-8-sig"
        ) as file:

            writer = csv.DictWriter(
                file,
                fieldnames=fields
            )

            writer.writeheader()
            writer.writerows(all_descriptions)

    print("\n==============================")
    print("AUTOMATION COMPLETED")
    print("==============================")
    print(f"Roles processed: {len(rows)}")
    print(f"JSON: {OUTPUT_JSON}")
    print(f"CSV : {OUTPUT_CSV}")


if __name__ == "__main__":
    main()