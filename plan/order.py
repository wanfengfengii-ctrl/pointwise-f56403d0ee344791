from dataclasses import dataclass

from score.cues import CueSource


@dataclass(frozen=True)
class PlannedCue:
    source: CueSource
    voice: str
    beat: int
    position: int
    text: str
    lamp: str

    @classmethod
    def from_record(cls, record):
        return cls(CueSource(**record['source']), record['voice'], record['beat'],
                   record['position'], record['text'], record['lamp'])


def order_cues(revision, drafts, targets):
    ordered = sorted(drafts, key=lambda cue: (cue.beat, cue.position))
    return tuple(PlannedCue(cue.source(revision), cue.voice, cue.beat, cue.position,
                            cue.text, targets[cue.cue_id]) for cue in ordered)
