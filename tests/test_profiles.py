from gcodeproducer.core import workflow as wf
from gcodeproducer.core.profiles import LibrarySet, Profile


def test_profile_resolve_defaults():
    p = Profile("nozzle", "0.4", values={"diameter": 0.4})
    r = p.resolved()
    assert r["diameter"] == 0.4
    assert r["line_width"] == 0.45          # default kept


def test_machine_allows(libset):
    m = libset.machines.get("generic-220-fdm")
    assert m.workflow == wf.FDM
    # default allowed_* == "*" -> everything allowed
    assert m.allows("material", "pla")
    assert m.allows("nozzle", "0-4-mm")


def test_machine_restricts_tools():
    m = Profile("machine", "CNC", workflow=wf.CAM, values={"allowed_tools": ["6-mm"]})
    assert m.allows("tool", "6-mm")
    assert not m.allows("tool", "3-mm")


def test_consumables_for_respects_workflow(libset):
    cnc = libset.machines.get("generic-300-router")
    # a CAM machine offers tools, not materials
    assert libset.consumables_for(cnc, "tool")
    assert libset.consumables_for(cnc, "material") == []


def test_library_roundtrip(tmp_path):
    ls = LibrarySet(tmp_path)
    ls["material"].add(Profile("material", "PLA", values={"temp_nozzle": 200}))
    ls.save()
    ls2 = LibrarySet(tmp_path).load()
    assert ls2["material"].get("pla").get("temp_nozzle") == 200
