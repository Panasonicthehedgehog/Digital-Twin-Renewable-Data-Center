from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_state_endpoint_returns_aggregates() -> None:
    response = client.get('/api/v1/state')
    assert response.status_code == 200
    payload = response.json()
    assert 'aggregates' in payload
    assert payload['aggregates']['facilityLoadKw'] > 0


def test_ingest_telemetry_updates_values() -> None:
    ingest = client.post(
        '/api/v1/telemetry',
        json={
            'halls': [{'id': 'hall-a', 'racks': [{'id': 'a-r1', 'cpuUtilization': 0.9, 'inletTempC': 28.2}]}],
            'weather': {'ambientTempC': 33.1},
        },
    )
    assert ingest.status_code == 200

    state = client.get('/api/v1/state').json()
    hall_a = next(h for h in state['halls'] if h['id'] == 'hall-a')
    rack = next(r for r in hall_a['racks'] if r['id'] == 'a-r1')
    assert rack['cpuUtilization'] == 0.9
    assert state['weather']['ambientTempC'] == 33.1


def test_bulk_endpoint_accepts_multiple_events() -> None:
    response = client.post(
        '/api/v1/telemetry/bulk',
        json=[
            {'grid': {'priceEurPerMwh': 180}},
            {'renewables': [{'id': 'solar-east', 'outputKw': 9000}]},
        ],
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload['events'] == 2
