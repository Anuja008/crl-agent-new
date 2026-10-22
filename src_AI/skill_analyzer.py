
import re


# Common technical skills to look for in job postings.
# These are candidates only; results are counted only when mentioned
# in the matching job data.
TECHNICAL_SKILLS = [
    "Python", "Java", "C++", "JavaScript", "TypeScript",
    "SQL", "MySQL", "PostgreSQL", "MongoDB",
    "HTML", "CSS", "React", "Node.js", "Django", "Flask",
    "FastAPI", "REST API", "Git", "GitHub",
    "Docker", "AWS", "Azure", "Linux",
    "Data Structures", "Algorithms", "OOP",
    "Machine Learning", "Pandas", "NumPy",
    "Excel", "Power BI", "Tableau",
]


def extract_skills(jobs, competencies):
    """Extract mentioned technical skills and CRL competencies."""

    columns = [
        col for col in ["title", "context"]
        if col in jobs.columns
    ]

    if not columns:
        return []

    job_text = jobs[columns].fillna("").astype(str).agg(
        " ".join, axis=1
    )

    results = {}

    # Search for technical skills mentioned in the postings.
    for skill in TECHNICAL_SKILLS:
        pattern = r"(?<!\w)" + re.escape(skill) + r"(?!\w)"

        count = int(
            job_text.str.contains(
                pattern, case=False, regex=True
            ).sum()
        )

        if count:
            results[skill.lower()] = {
                "skill": skill,
                "job_count": count,
                "source": "job_postings",
            }

    # Also include competencies from your existing dictionary.
    if "Competency" in competencies.columns:
        for value in competencies["Competency"].dropna():
            skill = str(value).strip()

            if not skill:
                continue

            pattern = r"(?<!\w)" + re.escape(skill) + r"(?!\w)"

            count = int(
                job_text.str.contains(
                    pattern, case=False, regex=True
                ).sum()
            )

            key = skill.lower()

            if count and key not in results:
                results[key] = {
                    "skill": skill,
                    "job_count": count,
                    "source": "job_postings",
                }

    return sorted(
        results.values(),
        key=lambda item: item["job_count"],
        reverse=True,
    )
