from PIL import Image

from portrait_composer.color_match import color_match_params, sample_patch
from portrait_composer.visual_ops import apply_visual_ops


def test_color_match_uses_patch_and_keeps_operation_non_destructive():
    source = Image.new("RGBA", (9, 9), (160, 80, 60, 255))
    target = Image.new("RGBA", (9, 9), (80, 120, 180, 255))
    assert sample_patch(source, (4, 4), radius=2) == (160, 80, 60)
    params = color_match_params((160, 80, 60), (80, 120, 180), strength=0.75)
    corrected = apply_visual_ops(source, [{"id": "match", "type": "color", "params": params}])
    assert corrected.getpixel((4, 4)) != source.getpixel((4, 4))
    assert source.getpixel((4, 4)) == (160, 80, 60, 255)
