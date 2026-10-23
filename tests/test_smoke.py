from coderogue.app import main


def test_import():
    import coderogue  # noqa: F401


def test_headless_run_on_test_map():
    assert main(["--headless-frames", "120", "--map", "content/maps/test_room.tmj"]) == 0


def test_headless_run_default_map():
    assert main(["--headless-frames", "5"]) == 0
