"""Hybrid milestone data layer for the ALLEN·I·VERSE project dashboard — the landing
page's data source. Prefers live ClickUp hierarchy (allen/tools_clickup.py) per
project when its ClickUp list is configured and reachable; falls back to manually
entered milestones (allen/db.py's project_milestones table, populated via the
project_milestone_step virtual form in chat) otherwise. Never fabricates progress —
a project with nothing tracked yet reports 0/0, the same honesty convention as
usage.py's "not yet reporting" state for projects with no billing activity."""

import logging

from . import db
from .config import settings
from .usage import PIAAR_PROJECTS

logger = logging.getLogger(__name__)


def _milestones_for(project: dict) -> list[dict]:
    """Hybrid lookup for one PIAAR_PROJECTS entry: live ClickUp hierarchy if the
    project's list is configured and ClickUp is reachable, else manual DB rows."""
    list_id = project.get("clickup_list_id")
    if list_id and settings.clickup_ready:
        from . import tools_clickup

        try:
            milestones = tools_clickup.get_clickup_milestones(list_id)
            if milestones:
                return milestones
        except Exception as exc:
            logger.warning("[dashboard] ClickUp milestone fetch failed for %s: %s", project["key"], exc)
            # fall through to manual data rather than breaking the dashboard

    rows = db.list_milestones(project["key"])
    out = []
    for r in rows:
        steps = r["steps"] or []
        out.append({
            "id": r["title"],
            "title": r["title"],
            "goal": r["goal"] or r["title"],
            "done": bool(steps) and all(s.get("done") for s in steps),
            "source": "manual",
            "steps": steps,
        })
    return out


def _progress(milestones: list[dict]) -> tuple[int, int]:
    total = sum(len(m["steps"]) for m in milestones)
    done = sum(1 for m in milestones for s in m["steps"] if s.get("done"))
    return done, total


def get_project_summaries() -> list[dict]:
    """One summary per PIAAR project, for the dashboard landing grid. A project with
    no milestones tracked yet still appears (0/0, "not yet tracked") — the shape is
    ready before the data is, same as PIAAR_PROJECTS' own docstring promises."""
    out = []
    for p in PIAAR_PROJECTS:
        milestones = _milestones_for(p)
        done, total = _progress(milestones)
        out.append({
            "key": p["key"],
            "label": p["label"],
            "division": p.get("division"),
            "milestone_count": len(milestones),
            "steps_done": done,
            "steps_total": total,
            "source": "clickup" if (p.get("clickup_list_id") and settings.clickup_ready and milestones) else "manual",
        })
    return out


def get_project_milestones(key: str) -> dict:
    """Full milestone/step detail for one project's drill-down view."""
    project = next((p for p in PIAAR_PROJECTS if p["key"] == key), None)
    if not project:
        return {"key": key, "label": key, "division": None, "milestones": []}
    return {
        "key": project["key"],
        "label": project["label"],
        "division": project.get("division"),
        "milestones": _milestones_for(project),
    }
