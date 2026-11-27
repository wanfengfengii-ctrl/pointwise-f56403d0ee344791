from dataclasses import dataclass

from common import ApiError, text
from score.cues import CueDraft


@dataclass(frozen=True)
class ScoreSection:
    name: str
    position: int


def index_sections(names):
    if not isinstance(names, list) or not names:
        raise ApiError(400, 'invalid_sections', 'Declare at least one named section')
    result = {}
    for position, raw_name in enumerate(names):
        name = text(raw_name, 'section name')
        if name in result:
            raise ApiError(400, 'duplicate_section', f'Duplicate section {name}')
        result[name] = ScoreSection(name, position)
    return result


def require_section(sections, name):
    for section in sections:
        if section.name == name:
            return section
    raise ApiError(404, 'unknown_section', f'Unknown selected section {name}')


def select_section_cues(sections, cues: tuple[CueDraft, ...], name):
    selected = require_section(sections, name)
    return tuple(cue for cue in cues if cue.section == selected.name)
