from coderogue.input.modes import Mode, ModeMachine


def test_count_prefix_parsing():
    mm = ModeMachine()
    assert mm.pending_count is None
    assert mm.feed_digit("1")
    assert mm.feed_digit("2")
    assert mm.pending_count == 12
    assert mm.take_count() == 12
    assert mm.take_count() == 1


def test_zero_alone_is_not_a_count_but_extends_one():
    mm = ModeMachine()
    assert not mm.feed_digit("0")
    assert mm.feed_digit("1")
    assert mm.feed_digit("0")
    assert mm.take_count() == 10


def test_non_digits_rejected_and_count_capped():
    mm = ModeMachine()
    assert not mm.feed_digit("j")
    assert not mm.feed_digit("")
    for _ in range(6):
        mm.feed_digit("9")
    assert mm.take_count() == 999


def test_escape_clears_count_and_mode():
    mm = ModeMachine()
    mm.feed_digit("3")
    mm.set_mode(Mode.INSERT)
    assert mm.pending_count is None
    assert not mm.feed_digit("4")  # digits are text in INSERT
    mm.escape()
    assert mm.mode is Mode.NORMAL


def test_command_line():
    mm = ModeMachine()
    mm.set_mode(Mode.COMMAND)
    mm.command_type("wq")
    mm.command_backspace()
    assert mm.command_buffer == "w"
    assert mm.command_submit() == "w"
    assert mm.mode is Mode.NORMAL
    mm.set_mode(Mode.COMMAND)
    mm.command_backspace()  # backspace on empty line leaves COMMAND
    assert mm.mode is Mode.NORMAL
