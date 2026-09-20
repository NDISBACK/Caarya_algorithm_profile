"""Posts three deliberately shaped students through the real API.

Each one is built to trigger a different branch of the algorithm, so running this
against a live server tells you at a glance whether the whole path - validation,
adaptive questioning, scoring, persistence, report - is behaving.

    python3 app.py            # in one terminal
    python3 seed_profiles.py  # in another
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:5000"

API = "api-development"
DB = "database-management"
AUTH = "authentication-user-management"


def request(path: str, payload: dict, method: str = "POST") -> dict:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        body = json.load(error)
        print(f"  ✗ {body.get('error')}")
        for detail in body.get("details", []):
            print(f"      · {detail}")
        raise SystemExit(1)
    except urllib.error.URLError:
        raise SystemExit(f"Nothing listening on {BASE}. Start the app first: python3 app.py")


def identity(name: str, email: str) -> dict:
    return {
        "full_name": name, "email": email, "phone": "9876543210",
        "city": "Pune", "state": "Maharashtra",
    }


def academics() -> dict:
    """Education is its own section in the form now, so it posts separately."""
    return {
        "college": "Symbiosis Institute of Technology", "degree": "B.Tech",
        "branch": "Computer Science", "current_year": "3rd year",
        "graduation_month": "May", "graduation_year": 2027,
    }


def run_rating_rounds(selections: dict, answer) -> dict:
    """Walk the adaptive questioning exactly as the wizard does: first the skills
    behind the choices, then whatever the server decides is worth asking next."""
    ratings: dict[str, int] = {}
    first = request("/api/skill-set", selections)
    for skill in first["path"]:
        ratings[skill["id"]] = answer(skill, 0)

    rounds = 0
    while True:
        batch = request("/api/skill-set/next", {"selections": selections, "ratings": ratings})
        if batch["done"]:
            break
        for skill in batch["skills"]:
            ratings[skill["id"]] = answer(skill, batch["round"])
        rounds += 1
        if rounds > 5:                       # the server caps this; belt and braces
            break
    return ratings


def submit(name: str, email: str, selections: dict, ratings: dict, extras: dict | None = None) -> dict:
    return request("/api/profile", {
        "identity": identity(name, email),
        "academics": academics(),
        "selections": selections,
        "ratings": ratings,
        **(extras or {}),
    })


# ------------------------------------------------------------------ students


def strong_fit() -> tuple[dict, dict]:
    """Solid on exactly the work they chose, with projects that back it up."""
    selections = {
        "role_id": "backend-development",
        "service_ids": [API],
        "vc_ids": ["vc-design-rest-apis", "vc-build-api-endpoints", "vc-test-apis",
                   "vc-create-api-documentation"],
    }
    pattern = [5, 4, 4, 3]
    counter = {"n": 0}

    def answer(skill, round_number):
        if round_number == 0:
            counter["n"] += 1
            return pattern[counter["n"] % len(pattern)]
        return 2

    details = {
        "tool_stack": {
            "Languages": ["JavaScript", "Python", "SQL"],
            "Backend frameworks": ["Node.js / Express", "Flask"],
            "Databases": ["PostgreSQL"],
            "Tools & practice": ["Git / GitHub", "Postman", "Swagger"],
        },
        "work_experience": {"work_experience": [{
            "organisation": "Tapri Labs", "title": "Backend intern", "engagement_type": "Internship",
            "start_date": "2026-01", "end_date": "2026-05", "ongoing": False,
            "description": "Built and documented the REST API for their vendor onboarding flow.",
            "tech": ["Node.js", "Express", "PostgreSQL", "Swagger", "Postman"],
        }]},
        "projects": {"projects": [{
            "title": "Mess menu API", "status": "Live / shipped",
            "description": "A REST API the hostel app calls for daily menus and feedback.",
            "your_role": "Everything - schema, endpoints, tests", "team": "Solo",
            "tech": ["Python", "Flask", "SQL", "pytest"], "link": "https://github.com/example/mess-api",
        }], "competitions": []},
        "engagement": {"engagement_types": ["Internship", "Part-time role"],
                       "hours_per_week": "15–20", "earliest_start": "2026-11-01",
                       "commitment_duration": "3–6 months"},
        "location_comp": {"work_mode": "Remote only", "relocate": "Only for the right role",
                          "stipend_expectation": "₹10k–20k/month"},
        "world": {"industries": ["EdTech", "SaaS & B2B software"], "causes": ["Education access"],
                  "team_size": "Small team (3–6)"},
        "work_style": {"direction": 70, "collaboration": 30, "pace": 50,
                       "variety": 25, "feedback": 15, "learning": 80},
    }
    return ("Ananya Rao", "ananya.rao@example.edu", selections, answer, details)


def mismatch():
    """Wants API work, but every answer points at databases and auth instead."""
    selections = {
        "role_id": "backend-development",
        "service_ids": [API],
        "vc_ids": ["vc-design-rest-apis", "vc-optimize-api-performance", "vc-create-api-documentation"],
    }

    def answer(skill, round_number):
        return 1 if round_number == 0 else 5

    details = {
        "tool_stack": {"Languages": ["Python", "SQL"], "Databases": ["PostgreSQL", "Redis"]},
        "projects": {"projects": [{
            "title": "College result scraper", "status": "Complete but not deployed",
            "description": "Pulls results into Postgres and keeps them in sync nightly.",
            "your_role": "Schema design and the sync job", "team": "Team of 2–3",
            "tech": ["Python", "PostgreSQL", "Redis", "cron"],
            "link": "https://github.com/example/scraper",
        }], "competitions": [{"name": "Smart India Hackathon", "kind": "Hackathon",
                              "outcome": "Finalist", "year": 2026}]},
        "engagement": {"engagement_types": ["Internship"], "hours_per_week": "20–30",
                       "earliest_start": "2026-12-01"},
        "location_comp": {"work_mode": "Hybrid"},
        "world": {"industries": ["FinTech"]},
    }
    return ("Dev Mehta", "dev.mehta@example.edu", selections, answer, details)


def over_rater():
    """Straight 5s and no profile behind them - aligned, but heavily caveated."""
    selections = {
        "role_id": "backend-development",
        "service_ids": [AUTH],
        "vc_ids": ["vc-build-signup-login", "vc-token-authentication", "vc-user-session-management"],
    }
    return ("Rhea Kapoor", "rhea.kapoor@example.edu", selections, lambda skill, r: 5, None)


def show(label: str, name: str, profile_id: int, report: dict) -> None:
    verdict = report["verdict"]
    grid = {key: [entry["name"] for entry in box] for key, box in report["grid"]["boxes"].items()}
    print(f"\n{label}: {name}  →  {BASE}/report/{profile_id}")
    print(f"  verdict     {verdict['code']} — {verdict['headline']}")
    print(f"  role fit    {report['role_fit']['score']} ({report['role_fit']['band_label']}), "
          f"{report['role_fit']['confidence'] * 100:.0f}% sure")
    print(f"  chosen      raw {report['selected_average']} / cautious {report['selected_cautious']}")
    print(f"  quality     {report['flags']['response_quality']}"
          + (f" — {'; '.join(report['flags']['response_notes'])}" if report["flags"]["response_notes"] else ""))
    for key, names in grid.items():
        if names:
            print(f"  {key:11} {', '.join(names)}")
    if verdict["alternatives"]:
        print("  suggested   " + ", ".join(f"{a['name']} ({a['fit']})" for a in verdict["alternatives"]))
    if report["flags"]["unevidenced_skills"]:
        names = [s["name"] for s in report["flags"]["unevidenced_skills"]]
        print(f"  unevidenced {len(names)}: {', '.join(names[:4])}{'…' if len(names) > 4 else ''}")
    first = (report["recommended_value_constructs"] or [{}])[0]
    if first.get("effort"):
        print(f"  start with  {first['name']} — {first['effort']['summary']}")


def main() -> None:
    for label, build in [("strong fit", strong_fit), ("mismatch", mismatch), ("over-rater", over_rater)]:
        name, email, selections, answer, details = build()
        ratings = run_rating_rounds(selections, answer)
        core = {k: v for k, v in (details or {}).items()
                if k in ("tool_stack", "work_experience", "projects", "leadership", "portfolio")}
        result = submit(name, email, selections, ratings, core)
        show(label, name, result["profile_id"], result["report"])
        print(f"  rated       {len(ratings)} skills in total")

        follow_up = {k: v for k, v in (details or {}).items()
                     if k in ("engagement", "location_comp", "world", "work_style", "motivation")}
        if follow_up:
            updated = request(f"/api/profile/{result['profile_id']}/details", follow_up, method="PATCH")
            before = result["report"]["role_fit"]["confidence"]
            after = updated["report"]["role_fit"]["confidence"]
            print(f"  + details   confidence {before * 100:.0f}% → {after * 100:.0f}%, "
                  f"{len(updated['report']['flags']['unevidenced_skills'])} skills still unevidenced")

    print(f"\nOpen any link above, or {BASE}/report/1?view=company for the company snapshot.")


if __name__ == "__main__":
    sys.exit(main())
