from dataclasses import dataclass

from common import ApiError, text
from score.cues import CueDraft


@dataclass(frozen=True)
class LampAssignment:
    voice: str
    lamp: str


def resolve_targets(cues: tuple[CueDraft, ...], assignments, roster):
    if not isinstance(assignments, dict):
        raise ApiError(400, 'invalid_assignments', 'assignments must map voices to lamp identifiers')
    normalized = {text(voice, 'voice'): LampAssignment(voice, text(lamp, 'lamp'))
                  for voice, lamp in assignments.items()}
    targets = {}
    for cue in cues:
        assignment = normalized.get(cue.voice)
        if assignment is None or assignment.lamp not in roster:
            raise ApiError(400, 'missing_target', f'No rostered lamp for voice {cue.voice}')
        targets[cue.cue_id] = assignment.lamp
    return targets
