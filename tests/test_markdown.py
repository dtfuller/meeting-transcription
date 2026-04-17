from app import markdown as md


def test_headings_and_lists():
    html = md.render("# Title\n\n- a\n- b\n")
    assert "<h1>" in html and "Title" in html
    assert "<li>" in html and ">a<" in html


def test_no_script_tags():
    html = md.render("<script>alert(1)</script>\n\nhi")
    assert "<script>" not in html
    assert "hi" in html
