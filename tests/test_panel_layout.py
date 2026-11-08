from panel_view import SCREEN_MARGIN, panel_height


def test_short_content_uses_its_own_height():
    assert panel_height(500, screen_height=800) == 500


def test_tall_content_is_capped_to_the_screen():
    assert panel_height(900, screen_height=800) == 800 - SCREEN_MARGIN
