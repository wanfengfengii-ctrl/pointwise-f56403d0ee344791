from dataclasses import dataclass

from common import ApiError, fields, text


@dataclass(frozen=True)
class CueSource:
    revision: int
    section: str
    cue_id: str


@dataclass(frozen=True)
class CueDraft:
    cue_id: str
    section: str
    voice: str
    beat: int
    position: int
    text: str

    def source(self, revision):
        return CueSource(revision, self.section, self.cue_id)


def validate_beat(value):
    if type(value) is not int or value < 0:
        raise ApiError(400, 'invalid_beat', 'A cue beat must be a nonnegative JSON integer')
    return value


def read_cue_drafts(raw_cues, sections):
    if not isinstance(raw_cues, list):
        raise ApiError(400, 'invalid_cues', 'cues must be a list')
    seen = set()
    drafts = []
    for position, entry in enumerate(raw_cues):
        fields(entry, ('id', 'section', 'voice', 'beat', 'text'))
        cue_id = text(entry['id'], 'cue id')
        section = text(entry['section'], 'cue section')
        if cue_id in seen:
            raise ApiError(400, 'duplicate_cue', f'Duplicate cue {cue_id}')
        if section not in sections:
            raise ApiError(400, 'unknown_section', f'Cue {cue_id} refers to undeclared section {section}')
        drafts.append(CueDraft(cue_id, section, text(entry['voice'], 'voice'),
                               validate_beat(entry['beat']), position, text(entry['text'], 'cue text')))
        seen.add(cue_id)
    return tuple(drafts)
