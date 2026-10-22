
def recommend_skills(skills, top_n=10):
    return skills[:top_n]


def get_crl_guidance(skill, crl_descriptions):
    matches = crl_descriptions[
        crl_descriptions["Competency"].astype(str).str.strip().str.lower()
        == skill.strip().lower()
    ]

    if matches.empty:
        return None

    row = matches.iloc[0]

    return {
        "level": row.get("CRL", ""),
        "level_name": row.get("Level name", ""),
        "description": row.get("Description", ""),
        "task": row.get("Typical task", ""),
    }


def format_recommendations(role, jobs, skills, crl_descriptions):
    if jobs.empty:
        return (
            f"# Fresher Study Roadmap: {role.title()}\n\n"
            "No matching jobs found. Try another role title."
        )

    lines = [
        f"# Fresher Study Roadmap: {role.title()}",
        "",
        "## 1. Job-market overview",
        f"- Matching job rows: **{len(jobs)}**",
        "- Recommendations are based on competencies mentioned "
        "in the matching postings.",
        "",
        "## 2. Competencies to learn",
    ]

    if not skills:
        lines.append(
            "No matching skills or competencies were found in these postings."
        )

    for index, item in enumerate(skills, start=1):
        skill = item["skill"]
        guidance = get_crl_guidance(skill, crl_descriptions)

        lines.extend([
            "",
            f"### {index}. {skill}",
            f"- **Job-market evidence:** Mentioned in "
            f"{item['job_count']} matching job rows.",
        ])

        if guidance:
            if guidance["description"]:
                lines.append(
                    f"- **What to understand:** {guidance['description']}"
                )
            if guidance["task"]:
                lines.append(
                    f"- **Practice task:** {guidance['task']}"
                )
            if guidance["level"] != "":
                lines.append(
                    f"- **CRL reference:** {guidance['level']} "
                    f"{guidance['level_name']}"
                )
        else:
            lines.append(
                "- **CRL guidance:** No matching competency description."
            )

    lines.extend([
        "",
        "## 3. Suggested learning order",
        "",
        "1. Begin with the highest-frequency competencies listed above.",
        "2. Understand each concept and practise small exercises.",
        "3. Complete a mini-project that demonstrates the skills.",
        "4. Compare your work with the relevant CRL descriptions.",
        "",
        "## 4. Before applying",
        "- Review the requirements in individual job postings.",
        "- Practise explaining your projects and technical decisions.",
        "- Use this roadmap as guidance, not as a guarantee of hiring.",
    ])

    return "\n".join(lines)
