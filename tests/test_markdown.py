from app import markdown as md


def test_headings_and_lists():
    html = md.render("# Title\n\n- a\n- b\n")
    assert "<h1>" in html and "Title" in html
    assert "<li>" in html and ">a<" in html


def test_no_script_tags():
    html = md.render("<script>alert(1)</script>\n\nhi")
    assert "<script>" not in html
    assert "hi" in html


def test_render_transcript_escapes_and_highlights_unknown_speakers():
    out = md.render_transcript(
        "[00:00:00 Unknown Speaker 1] <b>hola</b>\n"
        "[00:01:00 Unknown Speaker 2] todo bien"
    )
    assert "<b>hola</b>" not in out
    assert "&lt;b&gt;hola&lt;/b&gt;" in out
    assert '<span class="unk">Unknown Speaker 1</span>' in out
    assert '<span class="unk">Unknown Speaker 2</span>' in out


def test_render_transcript_handles_empty_input():
    assert md.render_transcript("") == ""
    assert md.render_transcript(None) == ""
