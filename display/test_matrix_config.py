import pytest

from display.matrix_config import MatrixConfig, parse_config


def test_wall_defaults_are_192_square():
    assert MatrixConfig().canvas_size == (192, 192)


@pytest.mark.parametrize("raw, size", [
    ({"chain_length": 1, "parallel": 1, "pixel_mapper": ""}, (64, 64)),
    ({"chain_length": 2, "parallel": 1, "pixel_mapper": ""}, (128, 64)),
    ({"chain_length": 2, "parallel": 1, "pixel_mapper": "Rotate:90"}, (64, 128)),
    ({"chain_length": 4, "parallel": 1, "pixel_mapper": "U-mapper"}, (128, 128)),
    ({"chain_length": 4, "parallel": 1, "pixel_mapper": "U-mapper;Rotate:180"}, (128, 128)),
    ({"panel_rows": 16, "panel_cols": 32, "chain_length": 6, "parallel": 1,
      "pixel_mapper": "Remap:64,48|0,0n"}, (64, 48)),
    ({"chain_length": 1, "parallel": 1, "canvas_width": 32, "canvas_height": 32}, (32, 32)),
])
def test_canvas_size(raw, size):
    assert parse_config(raw).canvas_size == size


def test_brightness_ceiling():
    cfg = parse_config({"max_brightness": 90})
    assert cfg.clamp_brightness(100) == 90
    assert cfg.clamp_brightness(20) == 20
    assert cfg.clamp_brightness(0) == 1


@pytest.mark.parametrize("raw", [{"chain": 2}, {"max_brightness": 0}, {"max_brightness": 101}])
def test_rejects_bad_config(raw):
    with pytest.raises(ValueError):
        parse_config(raw)
