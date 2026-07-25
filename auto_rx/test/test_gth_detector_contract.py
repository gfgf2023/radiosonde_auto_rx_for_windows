import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _string_literal_value(source, variable):
    match = re.search(
        rf"static char {variable}\[\]\s*=\s*(.*?);",
        source,
        flags=re.DOTALL,
    )
    assert match is not None
    return "".join(re.findall(r'"([01]+)"', match.group(1)))


def test_gth_detector_matches_the_proven_decoder_sync_profile():
    detector = (ROOT / "scan" / "dft_detect.c").read_text()
    decoder = (ROOT / "demod" / "mod" / "cf06ht03mod.c").read_text()

    assert _string_literal_value(detector, "cf06ht03_header") == (
        _string_literal_value(decoder, "cf06ht03_header")
    )
    assert re.search(
        r'\{\s*2400,.*cf06ht03_header,\s*1\.0,\s*0\.0,\s*0\.70,\s*4,'
        r'.*"CF6GTH"',
        detector,
    )
