import re
from django import template

register = template.Library()


@register.filter(name='compact_preview')
def compact_preview(text, max_chars=400):
    """Strip markdown syntax and collapse whitespace for card preview."""
    if not text:
        return ''
    t = str(text)
    t = re.sub(r'^#{1,6}\s+', '', t, flags=re.MULTILINE)
    t = re.sub(r'\*{1,3}|_{1,3}', '', t)
    t = re.sub(r'^\s*[-*+]\s+', '', t, flags=re.MULTILINE)
    t = re.sub(r'\|', ' ', t)
    t = re.sub(r'`+', '', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t[:int(max_chars)]
