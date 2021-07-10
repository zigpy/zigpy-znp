from zigpy_znp.tools.common import UnclosableFile


def test_unclosable_file(tmp_path):
    path = tmp_path / "test.txt"
    f = path.open("w")

    with UnclosableFile(f) as unclosable_f:
        unclosable_f.write("test")
        unclosable_f.close()

    assert unclosable_f.f is f
    assert not unclosable_f.closed
    assert not f.closed

    f.close()

    assert unclosable_f.closed
    assert f.closed

    assert path.read_text() == "test"
