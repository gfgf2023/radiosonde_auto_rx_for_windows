import pytest

from autorx.scan import parse_dft_detect_output


@pytest.mark.parametrize(
    ("detector_type", "expected_type"),
    [
        ("RS41", "RS41"),
        ("RS92", "RS92"),
        ("DFM9", "DFM"),
        ("M10", "M10"),
        ("M20", "M20"),
        ("IMET4", "IMET"),
        ("IMET1RS", "IMET"),
        ("IMETafsk", "IMET1"),
        ("IMET5", "IMET5"),
        ("LMS6", "LMS6"),
        ("C34C50", "SRSC50"),
        ("MRZ", "MRZ"),
        ("MK2LMS", "MK2LMS"),
        ("MEISEI", "MEISEI"),
        ("MTS01", "MTS01"),
        ("WXR301", "WXR301"),
        ("WXRPN9", "WXRPN9"),
        ("RD94RD41", "RD94RD41"),
        ("CF6GTH", "CF6GTH"),
    ],
)
def test_parse_dft_detect_output_preserves_single_result_mappings(
    detector_type, expected_type
):
    detected_type, _ = parse_dft_detect_output(
        f"{detector_type}: 0.7500, +1250.0Hz\n", "test"
    )

    assert detected_type == expected_type


def test_parse_dft_detect_output_selects_highest_absolute_correlation():
    output = (
        "DFM9: 0.7100, +0.0Hz\n"
        "CF6GTH: 0.9500, -2000.0Hz\n"
        "RS41: -0.8000, +500.0Hz\n"
    )

    assert parse_dft_detect_output(output, "test") == ("CF6GTH", -2000.0)


def test_parse_dft_detect_output_preserves_strongest_inverted_result():
    output = "RS41: 0.7500\nMRZ: -0.9000\n"

    assert parse_dft_detect_output(output, "test") == ("-MRZ", 0.0)
