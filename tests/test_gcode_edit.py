from qt_app.gcode_edit import add_line_numbers, remove_line_numbers, replace_all


def test_remove_line_numbers_only_at_start_of_block() -> None:
    source = "N10 G01 X1\n  n20 M30\n(COMMENT N30)\nX2 N40"
    assert remove_line_numbers(source) == "G01 X1\n  M30\n(COMMENT N30)\nX2 N40"


def test_add_line_numbers_preserves_empty_and_percent_lines() -> None:
    source = "%\nO0001\n\nN900 G00 X0\n%"
    assert add_line_numbers(source) == "%\nN10 O0001\n\nN20 G00 X0\n%"


def test_replace_all_ignores_empty_search() -> None:
    assert replace_all("G00 X0", "", "M30") == "G00 X0"
    assert replace_all("G00 X0\nG00 X1", "G00", "G01") == "G01 X0\nG01 X1"
