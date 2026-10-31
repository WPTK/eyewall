"""Every saved payload is accounted for, unchanged, and parses; the recorder script's helpers work."""

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from eyewall.models.storm import AdvNum
from eyewall.providers.nhc import atcf, gis, graphics, tcm, text, two
from eyewall.providers.nhc.alerts import parse_alerts, parse_product, parse_product_list
from eyewall.providers.nhc.current import parse_current_storms
from tests.nhc_fixtures import FIXTURES, GIS, NHC

ROOT = Path(__file__).resolve().parents[1]
CR = bytes([13])
MANIFEST = json.loads((NHC / "sources.json").read_text(encoding="utf-8"))


def _load_recorder():
    spec = importlib.util.spec_from_file_location("record_fixtures", ROOT / "scripts" / "record_fixtures.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["record_fixtures"] = module
    spec.loader.exec_module(module)
    return module


recorder = _load_recorder()


def _fixture_files() -> list[str]:
    files = [p for root in (NHC, GIS) for p in root.rglob("*") if p.is_file()]
    return sorted(p.relative_to(FIXTURES).as_posix() for p in files if p.name != "sources.json")


# ---- bookkeeping --------------------------------------------------------------------------------------------------


def test_every_fixture_has_a_manifest_entry_and_every_entry_a_file():
    assert _fixture_files() == sorted(MANIFEST)


def test_recorded_fixtures_are_byte_for_byte_what_was_recorded():
    changed = []
    for path, entry in MANIFEST.items():
        if entry["source"] == "hand-built":
            continue
        digest = hashlib.sha256((FIXTURES / path).read_bytes()).hexdigest()
        if digest != entry["sha256"]:
            changed.append(path)
    assert changed == []


def test_hand_built_fixtures_say_why():
    hand_built = {path: entry for path, entry in MANIFEST.items() if entry["source"] == "hand-built"}
    assert set(hand_built) == set(recorder.HAND_BUILT)
    assert all(len(entry["note"]) > 40 for entry in hand_built.values())


def test_recorded_entries_name_a_url_and_a_time():
    for path, entry in MANIFEST.items():
        if entry["source"] != "hand-built":
            assert entry["source"].startswith("https://"), path
            assert entry["recorded"].endswith("Z"), path


def test_files_written_by_this_repo_use_lf_line_endings():
    # Recorded payloads keep whatever the server sent (NESDIS listings use CRLF); what we write ourselves is LF.
    written = [path for path, entry in MANIFEST.items() if entry["source"] == "hand-built"] + ["nhc/sources.json"]
    for path in written:
        assert CR not in (FIXTURES / path).read_bytes(), path


def test_committed_recipes_cover_every_recorded_fixture():
    recipe_paths = {r.path for r in recorder.committed_recipes()}
    recipe_paths |= {r.list_path for r in recorder.committed_recipes() if r.list_path}
    assert len(recipe_paths) == len(recorder.committed_recipes()) + sum(
        1 for r in recorder.committed_recipes() if r.list_path
    )  # no two recipes write the same file
    recorded = {path for path, entry in MANIFEST.items() if entry["source"] != "hand-built"}
    assert recorded == recipe_paths


# ---- every fixture parses -----------------------------------------------------------------------------------------

PARSERS = {
    "nhc/tcm": tcm.parse_tcm,
    "nhc/tcp": text.parse_tcp,
    "nhc/tcd": text.parse_tcd,
    "nhc/pws": text.parse_pws,
    "nhc/two": text.parse_two,
    "nhc/atcf": atcf.parse_bdeck,
}


@pytest.mark.parametrize("path", [p for p in _fixture_files() if p.rsplit("/", 1)[0] in PARSERS and "index" not in p])
def test_every_text_fixture_parses(path):
    parsed = PARSERS[path.rsplit("/", 1)[0]]((FIXTURES / path).read_bytes())
    assert parsed is not None


@pytest.mark.parametrize("path", [p for p in _fixture_files() if p.startswith("gis/")])
def test_every_zip_fixture_parses_with_the_matching_parser(path):
    data = (FIXTURES / path).read_bytes()
    name = Path(path).name
    if "5day" in name:
        assert gis.parse_forecast_zip(data).points
    elif "fcst" in name:
        assert gis.parse_radii_zip(data).initial
    elif "best_track" in name:
        assert gis.parse_best_track_zip(data).points
    else:
        assert name.startswith("gtwo_")
        assert two.parse_gtwo_zip(data).issued is not None


def test_json_and_html_fixtures_parse():
    assert parse_current_storms((NHC / "current/empty.json").read_bytes()).storms == ()
    assert len(parse_current_storms((NHC / "current/populated.json").read_bytes()).storms) == 4
    assert parse_alerts((NHC / "api/alerts_active_none.json").read_bytes()).alerts == ()
    assert len(parse_alerts((NHC / "api/alerts_populated.json").read_bytes()).alerts) == 2
    assert parse_product_list((NHC / "api/products_two_at.json").read_bytes())
    assert parse_product_list((NHC / "api/products_tcm_ep2.json").read_bytes())
    assert parse_product((NHC / "api/product_two_at.json").read_bytes()).text
    assert atcf.parse_btk_index((NHC / "atcf/btk_index.html").read_bytes())
    assert graphics.parse_floater_storms((NHC / "graphics/floater_root.html").read_bytes())
    assert graphics.parse_floater_products((NHC / "graphics/floater_cp032026.html").read_bytes())


def test_the_odd_cases_the_milestone_lists_are_all_covered():
    """no storms, a PTC, post-tropical, ep id in a CP bin, missing radii, DISSIPATED, E longitude, A intermediate zip."""
    current = parse_current_storms((NHC / "current/populated.json").read_bytes())
    assert parse_current_storms((NHC / "current/empty.json").read_bytes()).storms == ()  # no storms
    assert any(s.is_potential for s in current.storms)  # a potential tropical cyclone
    assert any(s.classification_text == "PC" for s in current.storms)  # post-tropical
    assert any(s.basin != s.bin_basin for s in current.storms)  # an ep id in a CP bin
    fay = tcm.parse_tcm((NHC / "tcm/fay_039.txt").read_bytes())
    assert fay.radii.empty and fay.post_tropical  # a TCM with missing radii
    assert any(f.dissipated for f in fay.fixes)  # DISSIPATED
    nolo = tcm.parse_tcm((NHC / "tcm/nolo_057.txt").read_bytes())
    assert nolo.lon == 180.0 and any(f.lon > 170 for f in nolo.fixes)  # an east longitude
    zip_ = gis.parse_forecast_zip((GIS / "erin_5day_030A.zip").read_bytes())
    assert zip_.adv_num == AdvNum(30, "A")  # an A intermediate zip


# ---- the recorder script ------------------------------------------------------------------------------------------


def test_archive_pages_are_reduced_to_the_product_text():
    page = b"<html><body><pre>\nZCZC MIATCMAT5 ALL\nSee <a href='x'>the link</a> &amp; more &lt;ok&gt;\nNNNN\n</pre></body></html>"
    assert recorder._pre_text(page) == b"ZCZC MIATCMAT5 ALL\nSee the link & more <ok>\nNNNN\n"
    with pytest.raises(ValueError):
        recorder._pre_text(b"<html>no product here</html>")


def test_the_english_outlook_is_picked_out_of_a_graphical_archive_page():
    page = (
        b"<pre>ZCZC MIATWOEP ALL<br>TTAA00 KNHC DDHHMM<br><br>Tropical Weather Outlook<br>english<br></pre>"
        b"<pre>496 ABPZ21 KNHC 100521TWOSEP Perspectiva</pre>"
        b"<pre>ZCZC MIATWOAT ALL<br>TTAA00 KNHC DDHHMM<br><br>Tropical Weather Outlook<br>atlantic</pre>"
    )
    assert recorder._two_text(page, "EP").endswith(b"english\n")
    assert recorder._two_text(page, "AT").endswith(b"atlantic\n")
    with pytest.raises(ValueError):
        recorder._two_text(page, "CP")


def test_storm_recipes_name_files_by_storm_and_advisory():
    recipes = recorder.storm_recipes("al052025", "erin", [AdvNum(30), AdvNum(30, "A")], "storm")
    paths = [r.path for r in recipes]
    assert "nhc/tcm/erin_030.txt" in paths and "nhc/pws/erin_030A.txt" in paths
    assert "gis/erin_5day_030A.zip" in paths and "gis/erin_fcst_030.zip" in paths
    assert "nhc/atcf/bal052025.dat.gz" in paths and "gis/erin_best_track.zip" in paths
    archive = next(r for r in recipes if r.path == "nhc/tcd/erin_030.txt")
    assert archive.url.endswith("/archive/2025/al05/al052025.discus.030.shtml")
    assert archive.transform == "pre"


def test_the_recorder_command_line_rejects_a_bad_advisory_number():
    with pytest.raises(SystemExit):
        recorder.main(["storm", "al052025", "--adv", "soon"])
