from zigpy_znp.types import nvids


def _test_nvid_uniqueness(nvids_table):
    seen = set()

    for attr in nvids_table:
        assert attr.value not in seen
        seen.add(attr.value)

    assert len(seen) == len(nvids_table)


def test_nvid_uniqueness():
    _test_nvid_uniqueness(nvids.ZclPortNvIds)
    _test_nvid_uniqueness(nvids.OsalExNvIds)
    _test_nvid_uniqueness(nvids.NwkNvIds)
