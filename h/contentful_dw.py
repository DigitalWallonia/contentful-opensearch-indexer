import sys
import aiohttp
import asyncio
import datetime

import h
import markdown
from . import colours
from . import opensearch_dw
from . import aws_dw

# --- Contentful settings
recursive_keys = ['title', 'slug', 'name', 'url', 'file', 'fileName', 'contentType', 'internalName', 'logoAssetImage', 'primaryColor', 'secondaryColor', 'id', 'quotedProfiles', 'role', 'clientSites']
cf_current_id = ''
cf_resolved_id = []
cf_include = 0
contentful_api = 'cdn.contentful.com'
contentful_space = 'myqv2p4gx62v'
recurse = 3
unavailable_cf_entry = []
currently_processed_entries = 0
currently_processed_entries_max = 500
contenttype_categories = {
    'fr': {
        'person': 'personnes',
        'program': 'programmes',
        'post': 'publications',
        'profile': 'cartographie',
        'event': 'agenda',
        'strategy': 'strategie'
    },
    'en': {
        'person': 'persons',
        'program': 'programs',
        'post': 'posts',
        'profile': 'cartography',
        'event': 'events',
        'strategy': 'strategy'
    }
}

# Categories dict generated by opn_build_categories
categories_dict = {}

# Current entry ID in a process
currently_resolved_entry = []
currently_indexed_entry = []

# Do not use caching
no_cache = True
request_timeout = 300000


# https://stackoverflow.com/questions/55704719/python-replace-values-in-nested-dictionary
async def dict_resolve_links(self, dictionary, linked_entries):
    """
    Iterate over each key of the :str `dictionary` and resolved the link if exists

    :param self:
    :param dictionary: the document on which we resolve links
    :param linked_entries: the links resolved
    :return:
    """
    x = {}
    for key, value in dictionary.items():
        if isinstance(value, dict):
            resolved_link_id = is_link(value)
            if resolved_link_id is not False:
                linked_entries.append(resolved_link_id)
                value = await cf_resolve_link(self, resolved_link_id)
            elif 'Geometry' in value:
                value = convert_to_geojson(value)
            else:
                value, linked_entries = await dict_resolve_links(self, value, linked_entries)
        elif isinstance(value, list):
            value, linked_entries_current = await list_resolve_links(self, value, linked_entries)
        x[key] = value
    return x, linked_entries


async def list_resolve_links(self, l, linked_entries):
    """
    Iterates over each entry in the list and processes it

    //// We should change the variable name

    :param self: the contentful client's class
    :param l: the list we iterate over
    :param linked_entries: the list of linked_entries
    :return:
    """
    x = []
    for e in l:
        if isinstance(e, list):
            e, linked_entries = await list_resolve_links(self, e, linked_entries)
        elif e is not None and 'Geometry' in e:
            e = convert_to_geojson(e)
        elif e is not None and isinstance(e, dict):
            resolved_link_id = is_link(e)
            if resolved_link_id is not False:
                linked_entries.append(resolved_link_id)
                e = await cf_resolve_link(self, resolved_link_id)
            else:
                e, linked_entries_current = await dict_resolve_links(self, e, linked_entries)
        x.append(e)
    return x, linked_entries


async def get_contentful_curl_rate_limit(self, entry_type, request_parameters):
    """
    Get a contentful entry and if a rate limit is hit, wait 0.25s and retries until the response code is not 429

    :param self: the contentful client's class
    :param entry_type: the entry tyoe we are searching for (assets or entries)
    :param request_parameters: the request parameters
    :return:
    """
    request_entry = await self.request_client.get(
        f"https://{contentful_api}/spaces/{contentful_space}/environments/{self.cf_env}/{entry_type}/?{request_parameters}")
    # Rate limit
    while request_entry.status == 429:
        # Store the rate limit message with timestamp
        rate_limit_message = f"{datetime.datetime.now().strftime('%m%d%Y%H%M%S%z')}: Received 429, retrying in 0.25s"
        # Append it to a file
        self.rate_limit_file.write(f"{rate_limit_message}\n")
        print(f"{colours.bcolors.WARNING}WARNING:{rate_limit_message}")
        await asyncio.sleep(0.25)
        request_entry = await self.request_client.get(
            f"https://{contentful_api}/spaces/{contentful_space}/environments/{self.cf_env}/{entry_type}/?{request_parameters}")
    return await request_entry.json(encoding="utf-8")


async def get_contentful_asset_entry_curl(self, cf_id='', param='', return_first=True, cf_link_type=''):
    """
    Returns entries from the CDA, if it exists.
    If the entry doesn't exist returns `None`

    :param
        `cf_id`: [str] contentful asset or entry ID
        `param`: [str] query strings and query parameters
        `return_first`: [bool] choose if `True` to return only the first result
    """
    # Check if the contenful ID doesn't exist in the CDA if `True` exit with `None`
    if cf_id in unavailable_cf_entry and no_cache is False:
        return None
    # If `cf_id` is `''` then let the user specifies its argument if not insert the ID
    request_parameters = self.param
    if cf_id != '':
        request_parameters += f"&sys.id={cf_id}"
    if param != '':
        request_parameters += f"{param}"
    # First do a search in entries then if null to assets as they are on different endpoints
    # If return_first only return the first element of all entries
    # Typically this is when you are looking for and ID
    if cf_link_type == 'Entry':
        current_request = await get_contentful_curl_rate_limit(self, 'entries', request_parameters)
    elif cf_link_type == 'Asset':
        current_request = await get_contentful_curl_rate_limit(self, 'assets', request_parameters)
    else:
        entry_request = await get_contentful_curl_rate_limit(self, 'entries', request_parameters)
        asset_request = await get_contentful_curl_rate_limit(self, 'assets', request_parameters)
        if entry_request['total'] != 0:
            current_request = entry_request
        else:
            current_request = asset_request
    if current_request['total'] == 0 and cf_id:
        print(f"{colours.bcolors.WARNING}Entry {cf_id} does not exists in the delivery")
        unavailable_cf_entry.append(cf_id)
        return None
    # If return_first only return the first element of all entries
    # Typically this is when you are looking for and ID
    if return_first:
        return current_request['items'][0]
    return current_request['items']


def is_link(dictionary):
    """
    Ugly function used to check if the entry is a link
    as the Contentful SDK cannot do it on its own well

    :param dictionary: [dict] the value you would like to check
    :return False not a link and the ID if is it a link
    """
    if 'sys' in dictionary:
        if 'linkType' in dictionary['sys']:
            if dictionary['sys']['id'] != cf_current_id and dictionary['sys']['linkType'] == 'Entry' or dictionary['sys']['linkType'] == 'Asset':
                return dictionary['sys']['id']
            else:
                return False
        else:
            return False
    else:
        return False


async def preprocess_document(self, doc):
    """
    Processes a document and post it to opensearch
    Processing means: converting the fields to GeoJSON and converting contentul richtext to HTML and plain text

    :param doc: entry to preprocess
    :return:
    """
    # Converts to GeoJSON
    if 'location' in doc['fields']:
        if 'Geometry' in doc['fields']['location']['fr']:
            doc['fields']['location']['fr']['Geometry']['type'] = 'Point'
            doc['fields']['location']['fr']['Geometry']['coordinates'] = [
                doc['fields']['location']['fr']['Geometry']['Location']['Lng'],
                doc['fields']['location']['fr']['Geometry']['Location']['Lat']
            ]
    return doc


def convert_to_geojson(value):
    """
    Converts a lighthouse entry to geojson

    :param value: the value of the lighthouse entry
    :return:
    """
    value['Geometry']['type'] = 'Point'
    value['Geometry']['coordinates'] = [
                value['Geometry']['Location']['Lng'],
                value['Geometry']['Location']['Lat']
                ]
    return value


async def retrieve_keys_from_dict(self, dictionary, keys):
    """
    Retrieves a selection of keys (from :var `keys`) from a dictionary. If it is a link resolve the link

    :param self:
    :param dictionary: the dictionary we wish to select key
    :param keys: the keys we want to select
    :return:
    """
    new_dict = {}
    for key in keys:
        if key in dictionary:
            if isinstance(dictionary[key]['fr'], dict):
                linked_entry_id = is_link(dictionary[key]['fr'])
                if linked_entry_id:
                    new_dict[key] = await cf_resolve_link(self, is_link(dictionary[key]['fr']))
                    if new_dict[key] is not None:
                        new_dict[key]['id'] = linked_entry_id
                else:
                    new_dict[key] = dictionary[key]
            else:
                new_dict[key] = dictionary[key]
    return new_dict


def set_no_cache(value):
    """
    Set the `no_cache` to a value

    :param value: the no_cache value we wish to set
    :return:
    """
    global no_cache
    no_cache = value


async def cf_resolve_link(self, cf_id, cf_fields=recursive_keys):
    """
        Get the Title, slug,...  from a Contentful entry as the SDK cannot do it on it's own
        Those returned elements are defined in `recursive_keys`

        :param
            * `cf_id`: [str] contentful ID
    """
    # If the contentful ID is not available in the CDA return None
    if cf_id in unavailable_cf_entry:
        return None
    # Try to get the entry in opensearch
    opn_fields = [f"fields.{k}.*" for k in recursive_keys]
    opn_entry = opensearch_dw.opn_get_document(self, cf_id, opn_fields)
    # If entry is not None means if the entry exists
    if opn_entry is not None:
        entry_currently_resolved = await retrieve_keys_from_dict(self, opn_entry['_source']['fields'], cf_fields)
        entry_currently_resolved['id'] = cf_id
        return entry_currently_resolved
    # If the entry doesn't exist in opensearch index it using only the CDA and therefore no cache
    elif no_cache or cf_id in cf_resolved_id or currently_processed_entries >= currently_processed_entries_max:
        request_entry = await get_contentful_asset_entry_curl(self, cf_id, return_first=True)
        if request_entry is None:
            return None
        entry_cda = await retrieve_keys_from_dict(self, request_entry['fields'], cf_fields)
        entry_cda['id'] = cf_id
        return entry_cda
    else:
        currently_resolved_entry.append(cf_id)
        print(f"{colours.bcolors.OKBLUE}Opensearch cache does not contains the entry {cf_id}, Indexing entry")
        cf_resolved_id.append(cf_id)
        opn_entry = await index_cf_entry(self, cf_id, return_document=True)
        if opn_entry is None:
            return None
        entry_currently_resolved = await retrieve_keys_from_dict(self, opn_entry['fields'], cf_fields)
        entry_currently_resolved['id'] = cf_id
        currently_resolved_entry.remove(cf_id)
        return entry_currently_resolved


# Index a single contentful entry in opensearch
async def index_cf_entry(self, cf_id, return_document=False):
    """
    Index an entry to opensearch

    :param self: cf_client
    :param cf_id: comtentful ID
    :param return_document: if `return_document` is `True` returns the whole processed document (as indexed)
    :return:
    """
    global currently_processed_entries
    global cf_current_id
    if cf_id in currently_indexed_entry:
        while cf_id in currently_indexed_entry:
            await asyncio.sleep(5)
        if not return_document:
            return 0
    currently_processed_entries += 1
    cf_current_id = cf_id
    # Get the entry on the CDA
    d = await get_contentful_asset_entry_curl(self, cf_id)
    # If the entry returned is None then it means it doesn't exist in the CDA (archived or draft for example)
    if d is None:
        self.unavailable_cf_entry.append(cf_id)
        print(f"{colours.bcolors.WARNING} {cf_id} could not be indexed")
        return None
    linked_entries = []
    # Build the category tree
    if 'categories' in d['fields'] and d['sys']['contentType']['sys']['id'] != 'category':
        d['fields']['categories']['fr'], linked_entries_temp = contentful_build_category_tree(d['fields']['categories']['fr'])
        linked_entries += linked_entries_temp
    # Resolve a specific case for the actionPlan profile when we want to resolve link 2 levels deep
    if d['sys']['type'] == 'Entry' and d['sys']['contentType']['sys']['id'] == 'actionPlan' and 'profiles' in d['fields']:
        cf_fields = recursive_keys + ['profile']
        linked_entries_temp = []
        new_profiles_list = []
        for entry_linked in d['fields']['profiles']['fr']:
            new_profiles_list.append(await cf_resolve_link(self, entry_linked['sys']['id'], cf_fields))
            linked_entries_temp.append(entry_linked['sys']['id'])
        d['fields']['profiles']['fr'] = new_profiles_list
        linked_entries += linked_entries_temp
    # Convert rich text to normal text
    if 'content' in d['fields']:
        if d['sys']['contentType']['sys']['id'] == 'contentBloc':
            for language, content in d['fields']['content'].items():
                d['fields']['content'][language] = markdown.markdown(content)
        elif d['sys']['contentType']['sys']['id'] != 'externalLink' and '</a>' not in d['fields']['content']['fr']:
            d['fields']['contentHTML'] = await h.convert_richtext2html(self, d['fields']['content'])
            d['fields']['content'] = h.convert_richtext2plain(d['fields']['content'])
    # Do the same conversion with the additional description
    if 'additionalDescription' in d['fields']:
        if 'fr' in d['fields']['additionalDescription'] or 'en' in d['fields']['additionalDescription']:
            d['fields']['additionalDescriptionHTML'] = await h.convert_richtext2html(self, d['fields']['additionalDescription'])
            d['fields']['additionalDescription'] = h.convert_richtext2plain(d['fields']['additionalDescription'])
    # Resolves all the linked_entries
    d['fields'], linked_entries_temp = await dict_resolve_links(self, d['fields'], [])
    # Correctly format the linkedentry list to avoid doublons
    linked_entries += linked_entries_temp
    d['linked_entries'] = list(dict.fromkeys(linked_entries))
    # Does the last bit of processing
    processed_document = await preprocess_document(self, d)
    # Then put the document in opensearch
    opensearch_dw.opn_put_document(self, processed_document)
    print(f"{colours.bcolors.OKGREEN}Entry {processed_document['sys']['id']} has been indexed")
    currently_processed_entries -= 1
    if return_document:
        return processed_document


def contentful_build_category_tree(contentful_entry_dict):
    """
    Builds the contentful tree using only the last categories

    :param contentful_entry_dict: the list of level 4 categories
    :return:
    """
    new_temp_dict = {}
    # Add all the categories to new_temp_dict
    linked_entries = []
    for category_link in contentful_entry_dict:
        if category_link['sys']['id'] in categories_dict:
            linked_entries.append(category_link['sys']['id'])
            new_temp_dict[category_link['sys']['id']] = categories_dict[category_link['sys']['id']]
    category_entry_list = []
    # The deepest level we could find categories as we need to recurse multiple times to avoid changing size dict
    category_level = 4
    # Let's add all the parents
    while category_level != 0:
        for category_id, category_fields in new_temp_dict.copy().items():
            if 'parents' in category_fields:
                for parent in category_fields['parents']:
                    if parent['id'] not in new_temp_dict:
                        linked_entries.append(parent['id'])
                        new_temp_dict[parent['id']] = categories_dict[parent['id']]
        category_level -= 1
    # Flatten the dict and remove the ID
    for category_id, category_fields in new_temp_dict.copy().items():
        category_entry_list.append(category_fields)
    return category_entry_list, linked_entries


def compare_opn_contentful_document(cf_document, opn_document):
    """
    Compares the cf_fields (usually the one we resolve) and checks if they are the same.
    If they are different sets `was_a_field_updated` to `True` and create a website redirection with the new slug

    :param cf_document: the contentful document (new)
    :param opn_document: the opensearch document (old)
    :return:
    """
    was_a_field_updated = False
    # The list of fields we want to compare
    cf_fields = ['title', 'slug', 'name', 'internalName', 'primaryColor', 'secondaryColor', 'id', 'role']
    for fields_compared in cf_fields:
        if fields_compared in cf_document['fields'] or fields_compared in opn_document['fields']:
            if cf_document['fields'][fields_compared] != opn_document['fields'][fields_compared]:
                print(f"cf fields {cf_document['fields'][fields_compared]} opn_fields {opn_document['fields'][fields_compared]}")
                was_a_field_updated = True
                print(f'{colours.bcolors.OKCYAN}fields are not the same')
                # Check to see if the slug changed
                if fields_compared == 'slug' and opn_document['sys']['contentType']['sys']['id'] in contenttype_categories['en']:
                    for language, slug in opn_document['fields']['slug'].items():
                        # Create the new URL
                        contenttype = contenttype_categories[language][opn_document['sys']['contentType']['sys']['id']]
                        old_slug = f"{language}/{contenttype}/{slug}"
                        new_slug = f"{language}/{contenttype}/{cf_document['fields']['slug'][language]}"
                        if old_slug != new_slug:
                            # Put the URL in S3
                            aws_dw.s3_put_website_redirect(old_slug, new_slug)
                            print(f"{colours.bcolors.OKCYAN} Changed {old_slug} to {new_slug}")
    return was_a_field_updated


class ContentfulResolveLink:
    """
    Class to resolve contentful links
    """
    def __init__(self, opn_client, cf_client):
        self.opn_client = opn_client
        self.cf_client = cf_client
        self.preprocessed_dictionary = {}


class ContentfulClient:
    """
    Class for the contentful connect client
    """
    def __init__(self, cf_clientid, cf_delivery_token, cf_env, opn_client):
        self.request_client = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=request_timeout))
        self.cf_env = cf_env
        self.param = f"access_token={cf_delivery_token}&include=0&locale=*"
        self.cf_current_id = ''
        self.opn_client = opn_client
        self.linked_entries = []
        self.opn_cf_index = f"d4w-entries_{cf_env}"
        self.unavailable_cf_entry = []
        self.rate_limit_file = open('rate_limit', 'a')
