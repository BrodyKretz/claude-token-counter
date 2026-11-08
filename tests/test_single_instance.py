from single_instance import acquire_lock


def test_second_lock_is_refused_until_first_is_released(tmp_path):
    path = tmp_path / "app.lock"
    first = acquire_lock(path)
    assert first is not None

    assert acquire_lock(path) is None

    first.close()
    again = acquire_lock(path)
    assert again is not None
    again.close()
