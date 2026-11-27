from dataclasses import asdict, dataclass

from common import ApiError, text
from plan.order import PlannedCue, order_cues
from plan.store import PreviewStore
from plan.targets import resolve_targets
from score.revisions import read_revision
from score.sections import select_section_cues


@dataclass(frozen=True)
class ShowPlan:
    show: str
    preview_id: int
    revision: int
    section: str
    assignments: dict[str, str]
    cues: tuple[PlannedCue, ...]


def freeze_preview(scores, previews: PreviewStore, show, revision, section, assignments, roster):
    score = read_revision(scores, show, revision)
    section = text(section, 'section')
    drafts = select_section_cues(score.sections, score.cues, section)
    targets = resolve_targets(drafts, assignments, roster)
    cues = order_cues(revision, drafts, targets)
    preview_id = previews.insert_preview(show, revision, section, assignments, [asdict(cue) for cue in cues])
    return ShowPlan(show, preview_id, revision, section, dict(assignments), cues)


def read_preview(previews: PreviewStore, show, preview_id):
    result = previews.load_preview(show, preview_id)
    if result is None:
        raise ApiError(404, 'unknown_preview', 'Unknown frozen preview for this show')
    revision, section, assignments, cues = result
    return ShowPlan(show, preview_id, revision, section, assignments,
                    tuple(PlannedCue.from_record(cue) for cue in cues))


def require_planned_cue(previews, show, preview_id, cue_id):
    for cue in read_preview(previews, show, preview_id).cues:
        if cue.source.cue_id == cue_id:
            return cue
    raise ApiError(404, 'unknown_planned_cue', 'Cue does not belong to the frozen preview')
