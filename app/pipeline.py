from app.anchors.match import match
from app.anchors.register import survey_book
from app.capture.scan import scan
from app.chainage.interpolate import restore
from app.coverage.balance import balance
from app.defects.cluster import consolidate

STAGES = ('capture', 'anchors', 'chainage', 'defects', 'coverage')


def recalculate(events, survey=None):
    marks, plan = survey if survey is not None else survey_book()
    anchors = match(events, marks)
    located = restore(events, anchors['anchors'])
    return {'anchors': anchors, 'chainage': located,
            'defects': consolidate(located['projected']),
            'coverage': balance(plan, located['segments'], located['gaps'])}


def inspect(raw, until='coverage', *, survey=None):
    captured = scan(raw)
    results = {'capture': captured}
    if until == 'capture':
        return results
    stages = recalculate(captured['events'], survey)
    results['anchors'] = stages['anchors']
    if until == 'anchors':
        return results
    results['chainage'] = stages['chainage']
    if until == 'chainage':
        return results
    results['defects'] = stages['defects']
    if until != 'coverage':
        return results
    results['coverage'] = stages['coverage']
    return results
