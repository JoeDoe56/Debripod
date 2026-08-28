import json

import requests

from debripod.Services.indexers.http_client import IndexerHttpClient
from debripod.Services.indexers.status import IndexerStatus


def test_persisted_cookies_and_user_agent_load_into_session():
    class Store:
        def get(self, _id):
            return IndexerStatus("demo", cookies_json=json.dumps([{"name": "clearance", "value": "ok", "domain": "tracker.test", "path": "/"}]), user_agent="Browser UA")
    session = requests.Session()
    IndexerHttpClient("demo", status_store=Store(), session=session)
    assert session.headers["User-Agent"] == "Browser UA"
    assert session.cookies.get("clearance", domain="tracker.test", path="/") == "ok"
