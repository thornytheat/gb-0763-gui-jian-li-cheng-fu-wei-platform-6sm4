import sqlite3

import pytest

from app.correction.revise import correct, listing


def archive_run(client, sample='dirty'):
    return client.post('/api/runs', json={'sample': sample}).json['run_id']


def test_correction_archives_recalc_batch(client):
    run_id = archive_run(client)
    result = client.post(f'/api/runs/{run_id}/corrections', json={'event_id': 'b0', 'odo_mm': 90000})
    assert result.status_code == 201
    body = result.json
    assert body['reused'] is False and body['parent_run_id'] == run_id
    assert body['affected_parts'] == [{'chain': 'UP-B', 'start_mm': 2000000, 'end_mm': 2100000}]
    detail = client.get(f"/api/runs/{run_id}/corrections/{body['correction_id']}").json
    reset = next(p for p in detail['stages']['chainage']['projected'] if p['event_id'] == 'p4')
    assert reset['station_mm'] == 2009091


def test_same_correction_replay_adds_no_archive(client):
    run_id = archive_run(client)
    first = client.post(f'/api/runs/{run_id}/corrections', json={'event_id': 'b0', 'odo_mm': 90000})
    second = client.post(f'/api/runs/{run_id}/corrections', json={'event_id': 'b0', 'odo_mm': 90000})
    assert (first.status_code, second.status_code) == (201, 200)
    assert second.json['correction_id'] == first.json['correction_id']
    assert len(client.get(f'/api/runs/{run_id}/corrections').json['corrections']) == 1


def test_failed_correction_rolls_back_then_retries(client, archive_app):
    run_id = archive_run(client)
    archive = archive_app.track_archive
    with archive.transaction() as db:
        db.execute("CREATE TRIGGER fail_correction BEFORE INSERT ON corrections BEGIN SELECT RAISE(ABORT, 'fault'); END")
    with pytest.raises(sqlite3.IntegrityError):
        correct(archive, run_id, {'event_id': 'b0', 'odo_mm': 90000})
    assert listing(archive, run_id)['corrections'] == []
    with archive.transaction() as db:
        db.execute('DROP TRIGGER fail_correction')
    assert correct(archive, run_id, {'event_id': 'b0', 'odo_mm': 90000})['reused'] is False
    assert len(listing(archive, run_id)['corrections']) == 1


def test_invalid_correction_can_be_retried(client):
    run_id = archive_run(client)
    bad = client.post(f'/api/runs/{run_id}/corrections', json={'event_id': 'b0', 'odo_mm': '九万'})
    assert (bad.status_code, bad.json['error']) == (422, 'BAD_BODY')
    empty = client.post(f'/api/runs/{run_id}/corrections', json={'event_id': 'b0'})
    assert (empty.status_code, empty.json['error']) == (422, 'BAD_BODY')
    assert client.post(f'/api/runs/{run_id}/corrections',
                       json={'event_id': 'b0', 'odo_mm': 90000}).status_code == 201


def test_correction_targets(client):
    run_id = archive_run(client)
    missing = client.post(f'/api/runs/{run_id}/corrections', json={'event_id': 'nope', 'odo_mm': 1})
    assert (missing.status_code, missing.json['error']) == (404, 'EVENT_MISSING')
    defect = client.post(f'/api/runs/{run_id}/corrections', json={'event_id': 'p1', 'odo_mm': 1})
    assert (defect.status_code, defect.json['error']) == (422, 'NOT_ANCHOR')
    gone = client.post('/api/runs/nope/corrections', json={'event_id': 'b0', 'odo_mm': 1})
    assert (gone.status_code, gone.json['error']) == (404, 'RUN_MISSING')
    assert client.get('/api/runs/nope/corrections').json['error'] == 'RUN_MISSING'
    assert client.get(f'/api/runs/{run_id}/corrections/nope').json['error'] == 'CORRECTION_MISSING'


def test_unmatched_anchor_keeps_full_validity(client):
    run_id = archive_run(client)
    result = client.post(f'/api/runs/{run_id}/corrections', json={'event_id': 'unknown', 'odo_mm': 115000})
    assert result.status_code == 201
    assert result.json['affected_parts'] == []
    assert result.json['valid_mm'] == 400000


def test_time_correction_recalculates(client):
    run_id = archive_run(client)
    result = client.post(f'/api/runs/{run_id}/corrections',
                         json={'event_id': 'b2', 'at': '2026-11-22T00:04:00Z'})
    assert result.status_code == 201
    assert result.json['summary']['mapped_mm'] == 500000
    assert result.json['affected_parts'] == [{'chain': 'UP-B', 'start_mm': 2300000, 'end_mm': 2400000}]


def test_validity_accumulates_corrections(client):
    run_id = archive_run(client)
    client.post(f'/api/runs/{run_id}/corrections', json={'event_id': 'b0', 'odo_mm': 90000})
    result = client.post(f'/api/runs/{run_id}/corrections', json={'event_id': 'b3', 'odo_mm': 520000})
    assert result.json['valid_mm'] == 200000
    parts = {(p['chain'], p['start_mm'], p['end_mm']) for p in result.json['valid_parts']}
    assert parts == {('UP-A', 1000000, 1100000), ('DN-A', 400000, 500000)}
    validity = client.get(f'/api/runs/{run_id}/validity').json
    assert validity['valid_mm'] == 200000 and len(validity['corrections']) == 2


def test_export_keeps_original_and_shows_validity(client):
    run_id = archive_run(client)
    client.post(f'/api/runs/{run_id}/issue')
    before = client.get(f'/api/runs/{run_id}/export').json
    assert before['verified'] and before['validity']['valid_mm'] == 400000
    client.post(f'/api/runs/{run_id}/corrections', json={'event_id': 'b0', 'odo_mm': 90000})
    after = client.get(f'/api/runs/{run_id}/export').json
    assert after['verified'] and after['seal'] == before['seal']
    assert after['evidence'] == before['evidence']
    assert after['validity']['valid_mm'] == 300000
    assert after['validity']['corrections'][0]['correction'] == {'event_id': 'b0', 'odo_mm': 90000}


def test_issue_page_marks_valid_range(client):
    run_id = archive_run(client)
    client.post(f'/api/runs/{run_id}/corrections', json={'event_id': 'b0', 'odo_mm': 90000})
    page = client.get(f'/work/issue?run={run_id}').get_data(as_text=True)
    assert '旧件有效范围' in page and '300000' in page
    assert '2300000 → 2400000' in page and '2000000 → 2100000' in page
