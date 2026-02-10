from fastapi.testclient import TestClient

from backend.app import app


client = TestClient(app)


def test_state_endpoint() -> None:
    response = client.get('/api/state')
    assert response.status_code == 200
    payload = response.json()
    assert 'loads' in payload
    assert payload['loads']['facility_kw'] > 0


def test_scenario_activation() -> None:
    response = client.post('/api/scenario', json={'name': 'combined_stress'})
    assert response.status_code == 200
    payload = response.json()
    assert payload['scenario'] == 'combined_stress'
    assert payload['state']['scenario'] == 'combined_stress'


def test_config_update() -> None:
    config = client.get('/api/config').json()
    config['energy']['grid_capacity_kw'] = 14000
    response = client.put('/api/config', json=config)
    assert response.status_code == 200
    payload = response.json()
    assert payload['config']['energy']['grid_capacity_kw'] == 14000
