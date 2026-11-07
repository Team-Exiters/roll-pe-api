from html import unescape

import nh3
from django.core.exceptions import ValidationError
from django.utils.html import strip_tags


cleaner = nh3.Cleaner(
    tags={'p', 'div', 'span', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'br', 'hr',
          'strong', 'b', 'em', 'i', 'u', 's', 'ul', 'ol', 'li', 'blockquote',
          'pre', 'code', 'a', 'table', 'thead', 'tbody', 'tr', 'th', 'td'},
    attributes={'a': {'href', 'title'}, 'th': {'colspan', 'rowspan'}, 'td': {'colspan', 'rowspan'}},
    set_tag_attribute_values={'a': {'target': '_blank'}},
    clean_content_tags={'script', 'style', 'iframe', 'object', 'svg', 'math', 'template'},
    url_schemes={'https', 'mailto'},
    url_relative='deny',
)


def clean_notice_html(value):
    html = cleaner.clean(value)
    if not unescape(strip_tags(html)).strip():
        raise ValidationError({'body': '공지 내용을 입력해주세요.'})
    return html
