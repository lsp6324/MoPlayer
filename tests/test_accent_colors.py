import pytest
from accent_colors import PRESETS, accent_roles, contrast, normalize_color


@pytest.mark.parametrize('value',['#12abEF','#000000','#ffffff'])
def test_rgb_normalization(value):
    assert normalize_color(value)==value.lower()


@pytest.mark.parametrize('value',['red','#fff','#12345678','rgb(1,2,3)',None,1])
def test_invalid_colors_cannot_enter_styles_or_preferences(value):
    with pytest.raises(ValueError):
        normalize_color(value)


@pytest.mark.parametrize('color',[value for name,value in PRESETS]+['#000000','#ffffff','#ffff00','#00ff00'])
@pytest.mark.parametrize('dark,surface',[(True,'#22262e'),(False,'#ffffff')])
def test_rgb_fill_is_preserved_with_readable_text_in_both_modes(color,dark,surface):
    roles=accent_roles(color,dark,surface)
    assert roles['button_fill']==color
    assert contrast(roles['accent'],surface)>=4.5
    assert contrast(roles['button_fill'],roles['button_text'])>=4.5
    assert contrast(roles['button_hover'],roles['button_text'])>=4.5
