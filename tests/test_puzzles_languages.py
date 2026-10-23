"""Language registry, command builders, version specs and Moth's error translations."""

from __future__ import annotations

import sys

import pytest

from coderogue.languages import (
    LANGUAGE_IDS,
    LanguageRuntime,
    available,
    get,
    parse_version,
    parse_version_spec,
    registry,
)


def test_registry_and_available() -> None:
    reg = registry()
    assert list(reg) == list(LANGUAGE_IDS) == ["python", "bash", "powershell"]
    assert {lang.file_name for lang in reg.values()} == {"main.py", "main.sh", "main.ps1"}
    assert "python" in available()
    for lang in reg.values():
        assert lang.highlight_keywords
        assert lang.display_name


def test_python_detect_uses_running_interpreter() -> None:
    rt = get("python").detect()
    assert rt is not None
    assert rt.executable == sys.executable
    assert rt.version[:2] == sys.version_info[:2]
    assert get("python").detect() is rt  # cached


def test_command_builders() -> None:
    py = get("python")
    assert py.command(LanguageRuntime("python", "/py", (3, 14)), "main.py") == [
        "/py", "-I", "-S", "-B", "-X", "utf8", "main.py"]
    bash = get("bash")
    assert bash.command(LanguageRuntime("bash", "/bin/bash", (3, 2)), "main.sh") == [
        "/bin/bash", "--noprofile", "--norc", "main.sh"]
    ps = get("powershell")
    assert ps.command(LanguageRuntime("powershell", "pwsh", (7, 4)), "main.ps1") == [
        "pwsh", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File",
        "main.ps1"]


def test_powershell_degrades_gracefully(monkeypatch: pytest.MonkeyPatch) -> None:
    from coderogue.languages import powershell

    monkeypatch.setattr(powershell.shutil, "which", lambda name: None)
    lang = powershell.PowerShellLanguage()
    assert lang.detect() is None


def test_bash_detect_parses_version() -> None:
    rt = get("bash").detect()
    if rt is None:
        pytest.skip("bash not installed")
    assert rt.version >= (3, 2)


def test_version_specs() -> None:
    bash5 = LanguageRuntime("bash", "b", (5, 3, 20))
    bash32 = LanguageRuntime("bash", "b", (3, 2, 57))
    lang = get("bash")
    assert lang.version_satisfies(bash5, ">=4")
    assert not lang.version_satisfies(bash32, ">=4")
    assert lang.version_satisfies(bash32, ">=3.2")
    assert lang.version_satisfies(bash32, "3.2")
    assert lang.version_satisfies(bash5, ">=4, <6")
    assert not lang.version_satisfies(bash5, "<5.3")
    assert parse_version("GNU bash, version 5.3.20(1)-release") == (5, 3, 20)
    with pytest.raises(ValueError):
        parse_version_spec("about four")


PY_ERRORS = [
    ('  File "main.py", line 2, in <module>\n    prnt("x")\n'
     "NameError: name 'prnt' is not defined. Did you mean: 'print'?\n",
     ["Line 2", "`prnt`", "`print`"]),
    ('  File "main.py", line 3, in <module>\nNameError: name \'nme\' is not defined\n',
     ["Line 3", "`nme`"]),
    ('  File "main.py", line 4\n    print("x)\nSyntaxError: unterminated string literal '
     "(detected at line 4)\n", ["Line 4", "quote"]),
    ('  File "main.py", line 1\nSyntaxError: \'(\' was never closed\n', ["`(`"]),
    ('  File "main.py", line 1\nSyntaxError: expected \':\'\n', ["colon"]),
    ('  File "main.py", line 2\nIndentationError: expected an indented block after \'if\'\n',
     ["Line 2", "indented"]),
    ('  File "main.py", line 1\nIndentationError: unexpected indent\n', ["extra indentation"]),
    ('  File "main.py", line 1\nSyntaxError: invalid syntax\n', ["could not read line 1"]),
    ('  File "main.py", line 5, in <module>\nZeroDivisionError: division by zero\n',
     ["Line 5", "zero"]),
    ("ValueError: invalid literal for int() with base 10: 'abc'\n", ["'abc'", "whole number"]),
    ('TypeError: can only concatenate str (not "int") to str\n', ["str(", "int"]),
    ("EOFError: EOF when reading a line\n", ["input()"]),
]


@pytest.mark.parametrize(("stderr", "fragments"), PY_ERRORS)
def test_python_translations(stderr: str, fragments: list[str]) -> None:
    text = get("python").translate_error(stderr)
    assert text is not None
    for frag in fragments:
        assert frag in text


BASH_ERRORS = [
    ("main.sh: line 2: ehco: command not found\n", ["Line 2", "`ehco`", "`echo`"]),
    ("main.sh: line 3: syntax error near unexpected token `fi'\nmain.sh: line 3: `fi'\n",
     ["`fi`", "; then"]),
    ("main.sh: line 3: syntax error near unexpected token 'done'\n", ["`done`", "do"]),
    ("main.sh: line 2: [: : integer expression expected\n", ["empty value", "spelled"]),
    ("main.sh: line 2: [: : integer expected\n", ["empty value"]),
    ("main.sh: line 5: zz: unbound variable\n", ["Line 5", "$zz"]),
    ("main.sh: line 4: unexpected EOF while looking for matching `\"'\n"
     "main.sh: line 5: syntax error: unexpected end of file\n", ["Line 4", "quote"]),
    ("main.sh: line 3: syntax error: unexpected end of file\n", ["fi", "done"]),
    ('main.sh: line 1: 5/0: division by 0 (error token is "0")\n', ["zero"]),
    ("main.sh: line 3: [: too many arguments\n", ["double quotes"]),
    ("main.sh: line 4: ${y^^}: bad substitution\n", ["`${y^^}`", "3.2"]),
    ("cat: nope.txt: No such file or directory\n", ["`nope.txt`"]),
]


@pytest.mark.parametrize(("stderr", "fragments"), BASH_ERRORS)
def test_bash_translations(stderr: str, fragments: list[str]) -> None:
    text = get("bash").translate_error(stderr)
    assert text is not None
    for frag in fragments:
        assert frag in text


PS_ERRORS = [
    ("Wirte-Output: The term 'Wirte-Output' is not recognized as a name of a cmdlet\n"
     "At main.ps1:3 char:1\n", ["Line 3", "`Write-Output`"]),
    ("The string is missing the terminator: \".\n", ["quote"]),
    ("RuntimeException: Attempted to divide by zero.\n", ["zero"]),
    ('Cannot convert value "abc" to type "System.Int32".\n', ["abc", "whole number"]),
    ("Missing closing '}' in statement block or type definition.\n", ["`}`"]),
]


@pytest.mark.parametrize(("stderr", "fragments"), PS_ERRORS)
def test_powershell_translations(stderr: str, fragments: list[str]) -> None:
    text = get("powershell").translate_error(stderr)
    assert text is not None
    for frag in fragments:
        assert frag in text


def test_unknown_errors_are_not_translated() -> None:
    for lang in registry().values():
        assert lang.translate_error("") is None
        assert lang.translate_error("something entirely new happened") is None


def test_windows_bash_skips_wsl_launcher_and_prefers_git_bash(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    import os
    import shutil as _shutil

    from coderogue.languages import bash as bashmod

    def touch(*parts: str) -> str:
        p = tmp_path.joinpath(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("")
        return str(p)

    wsl = touch("Windows", "System32", "bash.exe")
    pf_usr = touch("PF", "Git", "usr", "bin", "bash.exe")  # only usr\bin exists under PF
    scoop_bin = touch("scoop", "Git", "bin", "bash.exe")
    scoop_git = touch("scoop", "Git", "cmd", "git.exe")
    monkeypatch.setattr(bashmod.sys, "platform", "win32")
    for var in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)", "LOCALAPPDATA"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "PF"))
    which = {"git": scoop_git, "bash": wsl}
    monkeypatch.setattr(_shutil, "which", lambda name: which.get(name))

    assert bashmod._bash_candidates() == [pf_usr, scoop_bin]
    assert bashmod._is_wsl_launcher(r"C:\Windows\System32\bash.exe")
    assert bashmod._is_wsl_launcher(r"C:\WINDOWS\Sysnative\bash.exe")
    assert not bashmod._is_wsl_launcher(r"C:\Program Files\Git\bin\bash.exe")

    # Only the WSL launcher on PATH and no Git anywhere: no bash at all.
    monkeypatch.setenv("ProgramFiles", str(tmp_path / "nowhere"))
    which.pop("git")
    assert bashmod._bash_candidates() == []
    assert os.path.isfile(wsl)
