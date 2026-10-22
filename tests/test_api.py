from fastapi.testclient import TestClient
import main

def test_ping_endpoint():
    with TestClient(main.app) as c:
        r=c.get('/ping');assert r.status_code==200 and r.json()['status']=='ok'

def test_health_endpoint():
    with TestClient(main.app) as c:
        r=c.get('/health');assert r.status_code==200 and 'components' in r.json()
