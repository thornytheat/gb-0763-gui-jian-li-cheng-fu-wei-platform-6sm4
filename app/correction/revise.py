from datetime import datetime, timezone
import json
from time import perf_counter

from app.anchors.register import survey_book
from app.archive.save import retrieve
from app.config import GAP_SECONDS, LATE_SECONDS, MERGE_MM, REVISION
from app.coverage.intervals import subtract, union
from app.errors import TrackError
from app.manifest import canonical, digest
from app.pipeline import recalculate

SUMMARY_KEYS = ('planned_mm', 'mapped_mm', 'missing_mm', 'overlap_mm')


def parse_patch(body):
    if not isinstance(body, dict) or set(body) - {'event_id', 'at', 'odo_mm'}:
        raise TrackError('BAD_BODY')
    event_id = body.get('event_id')
    if not isinstance(event_id, str) or not event_id.strip():
        raise TrackError('BAD_BODY')
    patch = {}
    if 'at' in body:
        try:
            moment = datetime.fromisoformat(body['at'])
            if moment.utcoffset() is None:
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise TrackError('BAD_BODY') from exc
        patch['at'] = moment.astimezone(timezone.utc).isoformat()
    if 'odo_mm' in body:
        odo = body['odo_mm']
        if isinstance(odo, bool) or not isinstance(odo, int) or not 0 <= odo <= 10**12:
            raise TrackError('BAD_BODY')
        patch['odo_mm'] = odo
    if not patch:
        raise TrackError('BAD_BODY')
    return event_id, patch


def affected_parts(stages, event_id):
    cuts = {}
    for span in stages['chainage']['segments']:
        left, right = span['left'], span['right']
        if event_id in (left['event_id'], right['event_id']):
            lo, hi = sorted((left['station_mm'], right['station_mm']))
            cuts.setdefault(left['chain'], []).append((lo, hi))
    return [{'chain': chain, 'start_mm': lo, 'end_mm': hi}
            for chain in sorted(cuts) for lo, hi in union(cuts[chain])]


def correct(archive, run_id, body):
    started = perf_counter()
    event_id, patch = parse_patch(body)
    snapshot = retrieve(archive, run_id)
    events = snapshot['stages']['capture']['events']
    target = next((event for event in events if event['event_id'] == event_id), None)
    if target is None:
        raise TrackError('EVENT_MISSING', 404)
    if target['kind'] != 'anchor':
        raise TrackError('NOT_ANCHOR')
    corrected = [dict(event, **patch) if event is target else event for event in events]
    stages = recalculate(corrected, survey_book())
    parameters = {'gap_s': GAP_SECONDS, 'late_s': LATE_SECONDS, 'merge_mm': MERGE_MM}
    identity = {'parent_run_id': run_id, 'correction': dict(patch, event_id=event_id),
                'revision': REVISION, 'parameters': parameters}
    correction_id = digest(canonical(identity))
    manifest = dict(identity, correction_id=correction_id,
                    created_at=datetime.now(timezone.utc).isoformat(),
                    elapsed_ms=round((perf_counter() - started) * 1000),
                    summary={key: stages['coverage'][key] for key in SUMMARY_KEYS})
    payload = {'manifest': manifest, 'stages': stages,
               'affected_parts': affected_parts(snapshot['stages'], event_id)}
    with archive.transaction() as db:
        inserted = db.execute('INSERT OR IGNORE INTO corrections VALUES (?, ?, ?)',
                              (correction_id, run_id, canonical(payload))).rowcount
        saved = json.loads(db.execute('SELECT payload FROM corrections WHERE id=?',
                                      (correction_id,)).fetchone()[0])
    current = validity(archive, run_id)
    return dict(saved['manifest'], affected_parts=saved['affected_parts'],
                valid_parts=current['valid_parts'], valid_mm=current['valid_mm'],
                reused=not bool(inserted))


def _payloads(archive, run_id):
    with archive.transaction() as db:
        rows = db.execute('SELECT payload FROM corrections WHERE run_id=? ORDER BY rowid',
                          (run_id,)).fetchall()
    return [json.loads(row[0]) for row in rows]


def listing(archive, run_id):
    retrieve(archive, run_id)
    items = [dict(payload['manifest'], affected_parts=payload['affected_parts'])
             for payload in _payloads(archive, run_id)]
    return {'run_id': run_id, 'corrections': items}


def detail(archive, run_id, correction_id):
    with archive.transaction() as db:
        row = db.execute('SELECT payload FROM corrections WHERE id=? AND run_id=?',
                         (correction_id, run_id)).fetchone()
    if row is None:
        raise TrackError('CORRECTION_MISSING', 404)
    return json.loads(row[0])


def validity(archive, run_id):
    snapshot = retrieve(archive, run_id)
    cuts = {}
    corrections = []
    for payload in _payloads(archive, run_id):
        corrections.append(dict(payload['manifest'], affected_parts=payload['affected_parts']))
        for part in payload['affected_parts']:
            cuts.setdefault(part['chain'], []).append((part['start_mm'], part['end_mm']))
    parts = []
    for track in snapshot['stages']['coverage']['tracks']:
        for lo, hi in subtract(track['mapped_parts'], cuts.get(track['chain'], [])):
            parts.append({'chain': track['chain'], 'start_mm': lo, 'end_mm': hi})
    return {'run_id': run_id, 'valid_parts': parts,
            'valid_mm': sum(part['end_mm'] - part['start_mm'] for part in parts),
            'corrections': corrections}
