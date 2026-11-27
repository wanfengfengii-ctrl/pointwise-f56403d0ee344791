from dataclasses import dataclass

from common import ApiError, text
from score.cues import CueDraft, read_cue_drafts
from score.sections import ScoreSection, index_sections
from score.store import ScoreStore


@dataclass(frozen=True)
class ScoreRevision:
    show: str
    revision: int
    sections: tuple[ScoreSection, ...]
    cues: tuple[CueDraft, ...]


def write_score(store: ScoreStore, show, raw_sections, raw_cues):
    show = text(show, 'show')
    section_index = index_sections(raw_sections)
    sections = tuple(section_index.values())
    cues = read_cue_drafts(raw_cues, section_index)
    revision = store.insert_revision(show, sections, cues)
    return ScoreRevision(show, revision, sections, cues)


def read_revision(store: ScoreStore, show, revision):
    result = store.load_revision(show, revision)
    if result is None:
        raise ApiError(404, 'unknown_revision', 'Unknown score revision for this show')
    sections, cues = result
    drafts = []
    for row in cues:
        values = dict(row)
        values['beat'] = int(values['beat'])
        drafts.append(CueDraft(**values))
    return ScoreRevision(show, revision, tuple(ScoreSection(**row) for row in sections), tuple(drafts))
