from app.pagination import paginate


def test_paginate_empty_list():
    pg = paginate([], page=1, per_page=20)
    assert pg.items == []
    assert pg.total == 0
    assert pg.total_pages == 1
    assert pg.page == 1
    assert not pg.has_prev
    assert not pg.has_next


def test_paginate_less_than_one_page():
    pg = paginate(list(range(5)), page=1, per_page=20)
    assert pg.items == [0, 1, 2, 3, 4]
    assert pg.total_pages == 1
    assert not pg.has_next


def test_paginate_middle_page():
    pg = paginate(list(range(25)), page=2, per_page=10)
    assert pg.items == list(range(10, 20))
    assert pg.page == 2
    assert pg.total_pages == 3
    assert pg.has_prev
    assert pg.has_next


def test_paginate_clamps_out_of_range_high():
    pg = paginate(list(range(15)), page=999, per_page=10)
    assert pg.page == 2  # clamped to last page
    assert pg.items == [10, 11, 12, 13, 14]
    assert not pg.has_next


def test_paginate_clamps_out_of_range_low():
    pg = paginate(list(range(15)), page=-5, per_page=10)
    assert pg.page == 1
    assert pg.items == list(range(10))


def test_paginate_handles_non_int_page():
    pg = paginate(list(range(5)), page="junk", per_page=10)
    assert pg.page == 1
