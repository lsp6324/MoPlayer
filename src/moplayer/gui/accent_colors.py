"""RGB preferences and readable theme roles, independent of widgets and storage."""
from functools import lru_cache
import re


DEFAULT_ACCENT = '#477ce5'
PRESETS = (('蓝色', DEFAULT_ACCENT), ('紫色', '#8b5cf6'), ('粉色', '#db4f96'),
           ('红色', '#dc4b57'), ('橙色', '#d97925'), ('黄色', '#d6ad24'),
           ('绿色', '#37a56a'), ('青色', '#159f9b'), ('天蓝', '#2999c7'), ('灰色', '#7a8393'))


def normalize_color(value):
    if not isinstance(value, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', value):
        raise ValueError('强调色必须是有效的 RGB 颜色。')
    return value.lower()


def rgb(value):
    value = normalize_color(value)
    return tuple(int(value[index:index+2], 16) for index in (1,3,5))


def blend(color, target, amount):
    return '#' + ''.join(f'{round(a+(b-a)*amount):02x}' for a,b in zip(rgb(color),rgb(target)))


def luminance(color):
    values = [channel/255 for channel in rgb(color)]
    return sum(weight * (value/12.92 if value <= .04045 else ((value+.055)/1.055)**2.4)
               for value,weight in zip(values,(.2126,.7152,.0722)))


def contrast(first, second):
    light,dark = sorted((luminance(first),luminance(second)),reverse=True)
    return (light+.05)/(dark+.05)


@lru_cache(maxsize=128)
def accent_roles(color, dark, surface):
    """Preserve the selected RGB fill, adapting text and subtle tinted roles."""
    color = normalize_color(color)
    destination = '#ffffff' if dark else '#000000'
    readable = color
    for step in range(101):
        readable = blend(color,destination,step/100)
        if contrast(readable,surface) >= 4.5:
            break
    foreground = '#ffffff' if contrast(color,'#ffffff') >= contrast(color,'#000000') else '#000000'
    hover = blend(color,'#000000' if foreground == '#ffffff' else '#ffffff',.12)
    return dict(accent=readable,accent_dark=blend(readable,destination,.12),
                accent_soft=blend(surface,color,.16 if dark else .10),
                accent_tint=blend(surface,color,.12 if dark else .08),
                accent_line=blend(surface,readable,.48),accent_ring=readable,
                progress=readable,selected=blend(surface,color,.20 if dark else .12),
                button_fill=color,button_hover=hover,button_text=foreground)
