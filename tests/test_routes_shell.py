def test_meetings_page_renders(client):
    r = client.get("/meetings")
    assert r.status_code == 200
    assert "Meetings" in r.text
    assert 'class="tab active"' in r.text


def test_speakers_page_renders(client):
    r = client.get("/speakers")
    assert r.status_code == 200
    assert "Speakers" in r.text


def test_pipeline_page_renders(client):
    r = client.get("/pipeline")
    assert r.status_code == 200
    assert "Pipeline" in r.text
