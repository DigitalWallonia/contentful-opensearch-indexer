import os
import sys

# Local import
from . import contentful_dw
from dotenv import load_dotenv


# Functions used to convert to plain text
def convert_richtext2plain(nested_dict):
    """
    Converts rich text to html by extracting the `value`fields.
    For all the languages in `nested_dict` sends the dict to :function `dict_it_rt`

    :param nested_dict:
    :return: full_text
    """
    full_text = {}
    for language in nested_dict:
        if isinstance(nested_dict[language], str):
            full_text[language] = nested_dict[language]
        else:
            full_text[language] = dict_it_rt(nested_dict[language], plain_text_string='')
    return full_text


def dict_it_rt(dictionary, plain_text_string):
    """
    Sends to :function `list_it_rt` if the content is a list, to itself if dict and extract the value if a string

    :param dictionary: the dictionary we want to iterate over
    :param plain_text_string: the string containing the plain text
    :return: the plain text converted text
    """
    for key, value in dictionary.items():
        if isinstance(value, dict):
            plain_text_string = dict_it_rt(value, plain_text_string)
        elif isinstance(value, list):
            plain_text_string = list_it_rt(value, plain_text_string)
        elif isinstance(value, str) and key == 'value':
            plain_text_string += value
    return plain_text_string


def list_it_rt(list_plain_text, plain_text_string):
    """
    Sends to :function `dict_it_rt` if the content of the list is a dict, if it is a list sends it to itselves

    :param list_plain_text: the list we iterate over
    :param plain_text_string: the plain text converted text
    :return: the plain text converted text
    """
    for item in list_plain_text:
        if isinstance(item, list):
            plain_text_string = list_it_rt(item, plain_text_string)
        elif isinstance(item, dict):
            plain_text_string = dict_it_rt(item, plain_text_string)
    return plain_text_string


async def iterate_and_convert_content(self, node, language):
    """
    Iterate over each node in rich text and sends it to :function `convert_rich_text2html` for further processing

    :param self: the contentful/opensearch client class
    :param node: the content of the node key
    :param language: the language we are currently resolving
    :return:
    """
    html_converted = ''
    for node_content in node:
        node_content = await convert_rich_text2html(self, node_content, language)
        if node_content is not None:
            html_converted += node_content
    return html_converted


async def convert_rich_text2html(self, node, language):
    """
    Converts rich text to html. Iterate over each node types and converts it to html

    :param self: the contentful/opensearch client class
    :param node: the content of the node key
    :param language: the language we are currently resolving
    :return: the html converted rich text
    """
    # Add support to linked_entries
    nodetype = node['nodeType']
    paragraph = ""
    language_resolved = language
    if 'heading-' in nodetype:
        header_level = nodetype.split('-')[1]
        return f"<h{header_level} class='d4entry-header'>{await iterate_and_convert_content(self,node['content'], language)}</h{header_level}>"
    elif nodetype == 'paragraph':
        return f"<p class='d4wentry-paragraph'>{await iterate_and_convert_content(self,node['content'], language)}</p>"
    elif nodetype == 'unordered-list':
        # Missing 1 level
        return f"<ul class='d4entry-unordered-list'>{await iterate_and_convert_content(self,node['content'], language)}</ul>"
    elif nodetype == 'ordered-list':
        return f"<ul class='d4entry-ordered-list'>{await iterate_and_convert_content(self, node['content'], language)}</ul>"
    elif nodetype == 'hr':
        return '<hr class="d4entry-h4">'
    elif nodetype == 'blockquote':
        return f'<blockquote class="d4entry-blockquote">{await iterate_and_convert_content(self,node["content"], language)}</blockquote>'
    elif nodetype == 'embedded-asset-block':
        entry_id = node['data']['target']['sys']['id']
        resolved_entry = await contentful_dw.get_contentful_asset_entry_curl(self, entry_id, cf_link_type=node['data']['target']['sys']['linkType'])
        if resolved_entry is None:
            return ''
        entry_type = resolved_entry['sys']['type']
        entry_url = f"https:{resolved_entry['fields']['file']['fr']['url']}"
        if 'image/' in resolved_entry['fields']['file']['fr']['contentType']:
            entry_alt = resolved_entry['fields']['file']['fr']['fileName'].split('.')[0]
            entry_size = resolved_entry['fields']['file']['fr']['details']['image']
            return (f'<div class="d4wentry-{entry_id} d4entry-{entry_type} d4entry-asset-block">'
                    f'<img '
                    f'class="d4wentry-id-{entry_id} d4entry-type-{entry_type}" '
                    f'src="{entry_url}" alt="{entry_alt} asset image" '
                    f'width="{entry_size["width"]}" '
                    f'height="{entry_size["height"]}" />'
                    f'</div>')
        elif resolved_entry['fields']['file']['fr']['contentType'] == 'application/pdf':
            pdf_title = resolved_entry['fields']['title'][language_resolved]
            return (f'<div class="d4wentry-{entry_id} d4entry-{entry_type} d4entry-asset-block">'
                    f'<a '
                    f'class="d4wentry-id-{entry_id} d4entry-type-{entry_type}" '
                    f'src="{entry_url}">'
                    f'{pdf_title}</a>'
                    f'</div>')
        else:
            print(resolved_entry)
            sys.exit(2)
    elif nodetype == 'embedded-entry-block':
        entry_id = node['data']['target']['sys']['id']
        resolved_entry = await contentful_dw.index_cf_entry(self, entry_id, True)
        if resolved_entry is None:
            return ''
        if 'logoAssetImage' in resolved_entry['fields']:
            entry_alt = resolved_entry['fields']['logoAssetImage']['fr']['title'][language_resolved]
            entry_url = f"https:{resolved_entry['fields']['logoAssetImage']['fr']['file'][language_resolved]['url']}"
            entry_size = resolved_entry['fields']['logoAssetImage']['fr']['file'][language_resolved]['details']['image']
            logo_asset = (f'<img '
            f'src="{entry_url}" alt="{entry_alt} asset image" '
            f'width="{entry_size["width"]}" '
            f'height="{entry_size["height"]}"/>')
        else:
            logo_asset = ''
        entry_type = node['data']['target']['sys']['linkType'].lower()
        entry_title = resolved_entry['fields']['title'][language_resolved]
        entry_contenttype = resolved_entry['sys']['contentType']['sys']['id']
        if resolved_entry['sys']['contentType']['sys']['id'] == 'externalLink':
            return f'<div class="d4wentry-id-{entry_id} d4entry-type-{entry_type} d4entry-embedded-content"><p class="d4entry-embedded-content-title">{entry_title}</p>{resolved_entry["fields"]["content"]["fr"]}</div>'
        entry_slug = resolved_entry['fields']['slug'][language_resolved]
        return (f'<div class="d4wentry-id-{entry_id} d4entry-type-{entry_type} d4entry-entry-block">'
                    f'<a href="/{entry_contenttype}/{entry_slug}">'
                    f'{entry_title}'
                    f'</a>{logo_asset}'
                    f'</div>')
    elif nodetype == 'embedded-entry-inline':
        entry_id = node['data']['target']['sys']['id']
        resolved_entry = await contentful_dw.get_contentful_asset_entry_curl(self, entry_id, cf_link_type=node['data']['target']['sys']['linkType'])
        if resolved_entry is None:
            return ''
        entry_type = resolved_entry['sys']['type'].lower()
        if 'title' in resolved_entry['fields']:
            entry_title = resolved_entry['fields']['title'][language_resolved]
        else:
            entry_title = resolved_entry['fields']['internalName']['fr']
        entry_contenttype = resolved_entry['sys']['contentType']['sys']['id']
        entry_slug = resolved_entry['fields']['slug'][language_resolved]
        return (
            f'<a class="d4wentry-id-{entry_id} d4entry-type-{entry_type} d4entry-entry-inline d4entry-entry-inline-title" href="/{entry_contenttype}/{entry_slug}">'
            f'{entry_title}'
            f'</a>')
            #   f'<div class="d4entry-entry-inline-shortdescription">{entry_short_description}</div>')

    elif nodetype == 'entry-hyperlink':
        entry_id = node['data']['target']['sys']['id']
        entry_type = node['data']['target']['sys']['linkType'].lower()
        resolved_entry = await contentful_dw.get_contentful_asset_entry_curl(
            self, entry_id, cf_link_type=node['data']['target']['sys']['linkType'])
        if resolved_entry is None:
            return f"<div class='d4entry-d4wentry-id-{entry_id} d4entry-type-{entry_type} d4entry-entry-hyperlink d4entry-entry-inline-title'>{await iterate_and_convert_content(self,node['content'], language)}</div>"
        entry_contenttype = resolved_entry['sys']['contentType']['sys']['id']
        if 'slug' in resolved_entry['fields'] and language in resolved_entry['fields']['slug']:
            entry_slug = resolved_entry['fields']['slug'][language]
        else:
            entry_slug = 'none'
        if 'title' in resolved_entry['fields'] and language_resolved in resolved_entry['fields']['title']:
            entry_title = resolved_entry['fields']['title'][language_resolved]
        else:
            entry_title = resolved_entry['fields']['internalName']['fr']
        converted_value = f"<a class='d4wentry-id-{entry_id} d4entry-type-{entry_type} d4entry-entry-hyperlink d4entry-entry-inline-title' href='/{entry_contenttype}/{entry_slug}'>{await iterate_and_convert_content(self,node['content'], language)}</a>"
        return converted_value
    elif nodetype == 'text':
        if len(node['marks']) >= 1:
            start_tag = ""
            end_tag = ""
            for text_type in node['marks']:
                if text_type['type'] == 'bold':
                    start_tag = "<strong class='d4wentry-font-bold'>" + start_tag
                    end_tag += "</strong>"
                elif text_type['type'] == 'italic':
                    start_tag = "<em class='d44entry-italic'>" + start_tag
                    end_tag += "</em>"
            return start_tag + node['value'] + end_tag
        else:
            return node['value']
    elif nodetype == 'asset-hyperlink':
        entry_id = node['data']['target']['sys']['id']
        entry_type = node['data']['target']['sys']['linkType'].lower()
        resolved_entry = await contentful_dw.get_contentful_asset_entry_curl(
            self, entry_id, cf_link_type=node['data']['target']['sys']['linkType'])
        if resolved_entry is None:
            return ''
        url = "https:" + resolved_entry['fields']['file']['fr']['url']
        return f"<a class='d4wentry-id-{entry_id} d4entry-type-{entry_type.lower()} d4entry-asset-hyperlink' href='{url}'>{await iterate_and_convert_content(self,node['content'], language)}</a>"
    elif nodetype == 'hyperlink':
        return f"<a class='d4wentry-hyperlink' href='{node['data']['uri']}'>{await iterate_and_convert_content(self,node['content'], language)}</a>"
    elif nodetype == 'list-item':
        return f"<li class='d4entry-list-item'>{await iterate_and_convert_content(self,node['content'], language)}</li>"
    elif nodetype == 'table':
        return f"<table class='d4entry-table'>{await iterate_and_convert_content(self,node['content'], language)}</table>"
    elif nodetype == 'table-row':
        return f"<tr class='d4entry-table-row'>{await iterate_and_convert_content(self,node['content'], language)}</tr>"
    elif nodetype == 'table-cell':
        return f"<td class='d4entry-table-cell'>{await iterate_and_convert_content(self,node['content'], language)}</td>"
    elif nodetype == 'table-header-cell':
        return f"<th class='d4entry-table-header-cell'>{await iterate_and_convert_content(self,node['content'], language)}</th>"

async def convert_richtext2html(self, rich_text):
    """
    Converts rich text to html and plain text, iterate over all the languages

    :param self: the contentful client class
    :param rich_text: the dictionary containing contentful rich text
    :return:
    """
    content_html = {}
    for language, content in rich_text.items():
        content_html[language] = await iterate_and_convert_content(self, content['content'], language)
    return content_html
