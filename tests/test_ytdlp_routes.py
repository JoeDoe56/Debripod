import debripod.auth as auth
import debripod.runtime_routes as routes


def _client(monkeypatch):
    monkeypatch.setattr(auth,"_find_user",lambda username:{"username":username,"password_hash":"test"})
    monkeypatch.setattr(routes,"ytdlp_list_formats",lambda url:[{"file_id":"1","name":"Audio","source_label":"SoundCloud" if "soundcloud" in url else "YouTube"}])
    monkeypatch.setattr(routes,"run_flat_entries",lambda url:[{"id":"v1","url":url,"title":"Entry"}])
    class Directory:
        def load_section(self,url,section):
            return [{"result_id":"soundcloud:song:1","provider_group":"ytdlp","source":"soundcloud","source_label":"SoundCloud","kind":"song","kind_label":"Songs","title":"Track","subtitle":"","artist":"","album":"","year":"","duration":0,"thumbnail":"","canonical_url":url,"stable_source_id":"1","search_blob":"track","filter_values":{"sources":["SoundCloud"],"types":["Songs"],"indexers":[],"media":["music"]},"match_confidence":1,"rank_score":1,"browse_available":False,"stream_available":True,"download_available":True,"files_loaded":False,"file_count":0,"size":0,"files":[],"provider_data":{"soundcloud_id":"1","permalink_url":url,"set_type":"","track_count":0}}]
    monkeypatch.setattr(routes,"SoundCloudDirectoryService",Directory)
    app=routes.create_app(); app.config.update(TESTING=True,SECRET_KEY="test"); client=app.test_client()
    with client.session_transaction() as session: session["username"]="tester"
    return client


def test_generic_files_and_legacy_youtube_alias_match(monkeypatch):
    client=_client(monkeypatch)
    generic=client.get("/api/ytdlp/files?url=https://youtube.test/watch?v=1").get_json()
    legacy=client.get("/api/youtube/files?url=https://youtube.test/watch?v=1").get_json()
    assert generic == legacy and generic["files"][0]["source_label"] == "YouTube"


def test_directory_and_soundcloud_routes_are_source_accurate(monkeypatch):
    client=_client(monkeypatch)
    assert client.get("/api/ytdlp/directory?url=https://youtube.test/playlist").get_json()["entries"][0]["id"] == "v1"
    payload=client.get("/api/soundcloud/artist-section?url=https://soundcloud.com/artist&section=tracks").get_json()
    assert payload["source"] == "soundcloud"
    assert payload["results"][0]["source"] == "soundcloud"
