import json
import logging
import os
import re
import sys
from opensearchpy import OpenSearch
import traceback

import h
from . import colours
from . import contentful_dw

# --- Opensearch settings
languages = ['de', 'en', 'fr', 'nl']
opn_mapping_path = 'mapping_opensearch.json'
opn_index_settings = {
                    "settings" : {
	                    "number_of_shards": 5,
	                    "number_of_replicas": 0,
                        "analysis": {
                            "normalizer": {
                                "ascii_normalizer": {
                                    "type": "custom",
                                    "char_filter": [],
                                    "filter": ["lowercase", "asciifolding"]
                                }
                            }
                        }
                    }
                }


def opn_connect(self):
    """
    Connect function for opensearch

    :param self:
    :return:
    """
    client = OpenSearch(
                        hosts = [{'host': self.opn_host, 'port': self.opn_port}],
                        http_compress=True,  # enables gzip compression for request bodies
                        http_auth=self.opn_auth,
                        # client_cert = client_cert_path,
                        # client_key = client_key_path,
                        use_ssl=True,
                        verify_certs=False,
                        ssl_assert_hostname=False,
                        ssl_show_warn=False,
                        # ca_certs = ca_certs_path
                        timeout=60
                    )
    return client


def opn_search_by_cf_id(self, document_id):
    """
    Returns a document from opensearch matching the `document_id`.
    If not found returns `None`

    :param self: the OpenSearch Client calss
    :param document_id: the document id to search
    :return: the document if exists or None if it doesn't exis
    """
    #
    query = {'size': 5, 'query': {'multi_match': {'query': document_id, 'fields': ['sys.id']}}}
    opn_response = self.opn_client.search(
        body=query,
        index=self.opn_cf_index
    )
    if opn_response['hits']['total']['value'] == 1:
        return opn_response['hits']['hits'][0]
    else:
        return None


def opn_generate_mappings():
    """
    # https://www.elastic.co/guide/en/elasticsearch/reference/current/analysis-lang-analyzer.html
    # https://www.elastic.co/guide/en/elasticsearch/reference/current/mapping.html
    Generates mapping for index replacing `"localization": "keyword"` in `opn_mapping` with the language

    :return: mapping
    """
    # Open template file
    opn_mapping_template = open(opn_mapping_path).read()
    # Define mapping types and analysers used in the template file
    mapping_types = ['text', 'keyword', 'date', 'text_multi', 'keyword_multi']
    analyser_languages = { "de": "german", "en": "english", "fr": "french", "nl": "dutch" }
    # For each mapping types replace it with all the languages
    for mapping_type in mapping_types:
        mapping = '"properties": {'
        for loop_language in languages:
            if mapping_type == 'text':
                mapping += f""""{loop_language}": {{"type": "{mapping_type}", "analyzer": "{analyser_languages[loop_language]}"}}"""
            elif mapping_type == 'text_multi':
                mapping += f""""{loop_language}": {{"type": "text", "analyzer": "{analyser_languages[loop_language]}", 
                            "fields":{{"raw":{{"type":  "keyword","normalizer": "ascii_normalizer"}}}} }}"""
            elif mapping_type == 'keyword_multi':
                mapping += f""""{loop_language}": {{"type": "keyword", "analyzer": "{analyser_languages[loop_language]}", 
                            "fields":{{"raw":{{"type":  "keyword", }}}} }}"""
            else:
                mapping += f""""{loop_language}": {{"type": "{mapping_type}"}}"""
            if loop_language != languages[-1]:
                mapping += ','
            else:
                mapping += '}'
        opn_mapping_template = re.sub(f"\"localization\": \"{mapping_type}\"", mapping, opn_mapping_template)
    return opn_mapping_template


def opn_create_new_index(self, indices, index_mapping):
    """
    Creates a new index, iterate from 0 untill when it finds a free index name (see line 1)

    :param self: opensearch connect
    :param indices: list of indices gathered before matching the pattern wanted
    :param index_mapping: the index template setting
    :return: the name
    """
    index_number = 0
    new_index = f"{self.opn_cf_index}v{index_number}"
    print(new_index)
    while new_index in indices:
        index_number += 1
        new_index = f"{self.opn_cf_index}v{index_number}"
    opn_index_settings['mappings'] = json.loads(index_mapping)
    self.opn_client.indices.create(body=opn_index_settings, index=new_index)
    return new_index


def opn_manage_aliases(self, alias, index, action='add'):
    """
    Creates a new alias

    :param self: the opensearch client class
    :param alias: the alias' name
    :param index: the index we wish to index
    :param action: add, delete, ... refer to the documentation for more details
    :return:
    """
    alias_body = {
        "actions": [
            {action: {"index": index, "alias": alias}}
        ]
    }
    self.opn_client.indices.update_aliases(body=alias_body)


def opn_reindex_and_alias(self, aliases, index_mapping):
    """
    Creates a new index following a pattern, reindex the content of the indices linked to the alias and unlink the old
    indices.

    :param self: opnsearch client class
    :param aliases:
    :param index_mapping: index mapping template
    :return:
    """
    indices = self.opn_client.indices.get_alias("*")
    # Create the new index and reindex
    self.opn_cf_index_new = opn_create_new_index(self, indices, index_mapping)
    # Finally alias the new index twice,
    #   opn_cf_index --> contentful-entries-{production,staging,dev}
    #   contentful-entries --> index where clientSite not == cf_client_site (for caching)
    opn_manage_aliases(self, self.opn_cf_index, self.opn_cf_index_new)
    # Reindex the new index using the old aliased indices
    for key, value in aliases.items():
        if len(value['aliases']) >= 1:
            print(f"{colours.bcolors.OKCYAN}Reindexing {key} to {self.opn_cf_index_new}")
            body = {
                "source": {"index": key},
                "dest": {"index": self.opn_cf_index_new}
            }
            self.opn_client.reindex(body=body, timeout='2m', request_timeout=5000)
            opn_manage_aliases(self, self.opn_cf_index, key, 'remove')
        else:
            print(f"{colours.bcolors.OKCYAN}{key} not part of the alias, skipping and deleting")
            self.opn_client.indices.delete(index=key, ignore=[400, 404])


def opn_update_mapping(self, force_alias=''):
    """
    Updates the opensearch mapping used for our purpose,
    As we sometimes need to reindex in order to update the mappings, it will check how many indices have this alias
    If more than 1 index use this alias it will create a new one and merge all the documents in the new index

    :return: nothing
    """
    # Load the mapping data
    opensearch_template = opn_generate_mappings()
    # Load the opensearch index used for contentful
    # Get the aliases used by our index
    aliases = self.opn_client.indices.get_alias(f"{self.opn_cf_index}*")
    print(f'{colours.bcolors.OKCYAN}Updating mappings')
    # If there are more than 1 index using this alias call :function opn_reindex_and_alias
    if force_alias:
        self.opn_cf_index_new = opn_create_new_index(self, [], opensearch_template)
        return self.opn_cf_index_new
    if len(aliases) > 1:
        opn_reindex_and_alias(self, aliases, opensearch_template)
    # If no index are using this alias create it
    elif len(aliases) == 0:
        self.opn_cf_index_new = opn_create_new_index(self, aliases, opensearch_template)
        opn_manage_aliases(self, self.opn_cf_index, f"{self.opn_cf_index}v0")
    # If 1 index use this alias try to update the mapping, if it fails (the mapping cannot be updated),
    # so reindex the content of the index in a new one
    elif len(aliases) == 1:
        self.opn_cf_index_new = next(iter(aliases))
        try:
            self.opn_client.indices.put_mapping(opensearch_template, index=self.opn_cf_index_new)
        except:
            print(f'{colours.bcolors.OKCYAN}Recreating index and aliasing as the mappings changed')
            opn_reindex_and_alias(self, aliases, opensearch_template)
        # Load the new index name in a global variable for us to use
    print(f"{colours.bcolors.OKGREEN}Updated mappings")
    print(f"{colours.bcolors.OKBLUE}index used: {self.opn_cf_index_new}")
    return self.opn_cf_index_new


def opn_put_document(self, document, index=''):
    """
    Put a document in OpenSearch using the document ID
    :param self:
    :param document: the document we want to put in OpenSearch
    :param index: the index that should be used, default to self.opn_cf_index if not specified
    :return:
    """
    if index == '':
        index = self.opn_cf_index
    response = self.opn_client.index(
        index=index,
        body=document,
        id=document['sys']['id'],
        refresh=True
    )
    return response


def opn_delete_document(self, document_id, index=''):
    """
    Delete a document in OpenSearch using the document ID

    :param self:
    :param document_id: the document we want to delete in OpenSearch
    :param index: the index that should be used, default to self.opn_cf_index if not specified
    :return:
    """
    if index == '':
        index = self.opn_cf_index
    response = self.opn_client.delete_by_query(
        index=index,
        body={"query": {"bool": {"must": [{"term": {"_id": document_id}}]}}},
        refresh=True
    )
    return response


def opn_delete_documents_by_contenttype(self, contenttype_id, index=''):
    """
    Delete all documents in OpenSearch matching the contentType ID

    :param self:
    :param contenttype_id: the contentType we want to delete in OpenSearch
    :param index: the index that should be used, default to self.opn_cf_index if not specified
    :return:
    """
    if index == '':
        index = self.opn_cf_index
    response = self.opn_client.delete_by_query(
        index=index,
        body={"query": {"match":  {"sys.contentType.sys.id": contenttype_id}}},
        refresh=True
    )
    return response


def opn_query_search_after_linked_entry(self, document_id, size=1000, search_after=0, index=''):
    """
    Scroll and get all documents with linked entries

    :param self: the opensearch client's class
    :param document_id: the document ID we wish to get all linked_entries of
    :param size: the result size
    :param search_after: the search after parameters from the previous requests
    :return:
    """
    opn_query = {"query": {"match": {"linked_entries": document_id}},
                 "_source": False, "sort": [{"fields.publishedDate.fr": "asc"}, {"_id": "desc"}],
                 "size": size}
    if search_after != 0:
        opn_query['search_after'] = search_after
    opn_entries = self.opn_client.search(
        body=opn_query,
        index=self.opn_cf_index,
        # search_after=search_after,
        size=size,
        request_timeout=120
    )
    return opn_entries['hits']['hits']


def opn_query_all_linked_entry(self, document_id):
    """
    Get all the ID of entries linked to `document_id`

    :param self: the opensearch connection class
    :param document_id: the document ID we want to get the linked_entries of
    :return: <list> of all ID linked
    """
    research_size = 1000
    opn_entries = opn_query_search_after_linked_entry(self, document_id, research_size)
    linked_entries_list = []
    # Loop while the length of the result `opn_entries` is less than `research_size`
    while len(opn_entries) > 0:
        for opn_entry in opn_entries:
            # Extract the ID and adds it to `linked_entries_list`
            linked_entries_list.append(opn_entry['_id'])
        opn_entries = opn_query_search_after_linked_entry(self, document_id, research_size, opn_entries[-1]['sort'])
    return linked_entries_list


def opn_get_document(self, cf_id, fields=['fields.*'], index=''):
    """
    Get a document from opensearch

    :param self: the opensearch client
    :param cf_id: the document ID to search
    :param fields: fields we should return by default all
    :param index: opensearch index used
    :return:
    """
    if index == '':
        index = self.opn_cf_index
    #query = {"query": {"match": {"_id": cf_id}}, "fields": fields, "_source": False}
    query = {"query": {"match": {"_id": cf_id}}, "_source": True}
    opn_response = self.opn_client.search(
        body=query,
        index=index,
        expand_wildcards="open"
    )
    if opn_response['hits']['total']['value'] == 1:
        return opn_response['hits']['hits'][0]
    else:
        return None


def opn_put_script(self, script_name, script_body):
    """
    Post a script in opensearch using the `script_name` [str] as ID.

    :param self: the opensearch client
    :param script_name: the id/name of the script
    :param script_body: the body of the script (usually in moustache)
    :return: the opensearch response
    """

    response = self.opn_client.put_script(
        id=script_name,
        body=script_body
    )
    return response


def opn_get_script(self, script_id):
    """
    Get a script in opensearch using the `script_name` [str] as ID.

    :param self: the opensearch client
    :param script_id:
    :return: the opensearch response
    """
    response = self.opn_client.get_script(
        id=script_id
    )
    return response


def opn_update_search_template(self):
    """
    Post all script templates found in the `directory` [var], it uses the filename as the script name

    It does not check if the script already exists

    :return: nothing
    """
    # Defines the directory to look into
    directory = 'template-opensearch'
    # for each file found, load it in a json object and post it
    for filename in os.listdir(directory):
        with open(os.path.join(directory, filename), encoding='utf-8', mode='r') as template_file:
            print(f"{colours.bcolors.OKGREEN}Updating Template Scripts {filename}")
            script_body = template_file.read()
            if '|' in script_body:
                print('converting file to escape mustache')
                new = open('temp', 'a')
                new.write(script_body.replace('\n', '').replace(' ', '').split('|')[0])
                new.write('"')
                new.write(script_body.replace('\n', '').replace(' ', '').split('|')[1].replace('"', '\\"'))
                new.write('"')
                new.write(script_body.replace('\n', '').replace(' ', '').split('|')[2])
                new.close()
                escaped_script_body_file = open("temp", "r")
                script_body = escaped_script_body_file.read()
                os.remove("temp")
                escaped_script_body_file.close()
            script_body = json.loads(script_body)
            opn_put_script(self, filename, script_body)


def opn_put_shape_template(self):
    """
    Create an index named `index` if it doesn't exist and
    post all documents under `directory` with their filename as ID.

    :return:
    """
    directory = 'shape-wallonia'
    index = 'shapes'
    # Shapes index setting including mapping
    opn_index_shapes_settings = {
        "settings": {
            "number_of_shards": 5,
            "number_of_replicas": 0,
            "analysis": {
                "normalizer": {
                    "ascii_normalizer": {
                        "type": "custom",
                        "char_filter": [],
                        "filter": ["lowercase", "asciifolding"]
                    }
                }
            }
        },
        "mappings": {
            "properties": {
                "location": {
                    "type": "geo_shape"
                }
            }
        }
    }
    # for each file found, load it in a json object and post it
    for filename in os.listdir(directory):
        with open(os.path.join(directory, filename), encoding='utf-8', mode='r') as template_file:
            print(f"{colours.bcolors.OKGREEN}Updating shape: {filename}")
            # Load json template_file
            script_body = json.load(template_file)
            # Adds the ID of the document
            script_body['sys'] = {'id': filename}
            # If the index doesn't exist create it
            if self.opn_client.indices.get(index='ds', allow_no_indices=True, ignore_unavailable=True) != {} :
                self.opn_client.indices.create(body=opn_index_shapes_settings, index=index)
            # Post the shapes into the index
            opn_put_document(self, script_body, index=index)


def opn_query_search_after(self, cf_type, size, search_after=0):
    """
    Equivalent to scrolling through the entries

    :param self: the opensearch client's class
    :param cf_type: the content type we wish to get the entries of
    :param size: the result size
    :param search_after: the search after parameters from the previous requests
    :return:
    """
    opn_query = {"query": {"match": {"sys.contentType.sys.id": cf_type}},
                 "_source": False, "sort": [{"fields.publishedDate.fr": "asc"}, {"_id": "desc"}],
                 "size": size}
    if search_after != 0:
        opn_query['search_after'] = search_after
    opn_entries = self.opn_client.search(
        body=opn_query,
        index=self.opn_cf_index,
        # search_after=search_after,
        size=size,
        request_timeout=120
    )
    return opn_entries


async def opn_build_categories(self):
    """
    Get all the opensearch categories

    :param self: the opensearch client
    :return:
    """
    index = self.opn_cf_index
    # We could use `fields` but they are not returned as dict so we use the source
    query = {"query": {"match": {"sys.contentType.sys.id": "category"}},
             "_source": True}
    opn_response = self.opn_client.search(
        body=query,
        index=index,
        size=5000,
        expand_wildcards="open"
    )
    if opn_response['hits']['total']['value'] < 1:
        print(f'{colours.bcolors.FAIL}No categories returned')
        sys.exit(1)
    # Create en empty dict
    categories_dict = {}
    # If this variable is set to true it means a new build took place
    new_category_tree_missing_category = False
    # The fields that we want to keep
    interesting_fields = ['title', 'slug', 'clientSitesList', 'children', 'isFeaturedOnProfilesSearchDW', 'id',
                          'isProfilesFilterOnProgramDW', 'isFeaturedOnProfileDw']
    # Iterates over all the responses from opensearch and build a dict in format
    # {"id": {<all the keys from `interesting_fields`>}}
    # If needed to understand put a print statement
    for category in opn_response['hits']['hits']:
        categories_dict[category["_id"]] = {}
        categories_dict[category["_id"]]['id'] = category["_id"]
        for field_name,field_value in category['_source']['fields'].items():
            # Copy the field to the new dict `categories_dict` only if field in `interesting_fields`
            if field_name in interesting_fields:
                categories_dict[category["_id"]][field_name] = field_value
    # Now creates the link between parent and children
    for category_id, category_fields in categories_dict.items():
        parent_entry = [{'title': category_fields['title'],'slug': category_fields['slug'], 'id': category_fields['id']}]
        # Check if the entry is a parent (so has `children`) then add the parent entry `interesting_fields` to the child
        if 'children' in category_fields:
            for category_children in category_fields['children']['fr']:
                # If for some reason a link is not resolved, index the entry and set it to category_children
                # so that the building can continue
                if category_children is not None and 'id' not in category_children:
                    print(f"{h.bcolors.WARNING}category hasn't been properly indexed, trying to reindex {category_fields['id']}")
                    # Reindex the parent entry containing the children
                    await h.index_cf_entry(self, category_fields['id'])
                    # Then relaunch a building of the categorytree
                    new_category_tree_missing_category = await opn_build_categories(self)
                elif category_children is not None and category_children['id'] in categories_dict:
                    if 'parents' not in categories_dict[category_children['id']]:
                        categories_dict[category_children['id']]['parents'] = []
                    if parent_entry[0] not in categories_dict[category_children['id']]['parents']:
                        categories_dict[category_children['id']]['parents'] += parent_entry
    # Export as a global var in :file `contentful_dw`
    if new_category_tree_missing_category:
        contentful_dw.categories_dict = new_category_tree_missing_category
    else:
        contentful_dw.categories_dict = categories_dict
    # Post the category tree to opensearch with id `categorytree`
    index = self.opn_cf_index
    response = self.opn_client.index(
        index=index,
        body={'categories': categories_dict},
        id='categorytree',
        refresh=True
    )
    return response


def opn_get_all_document_id_from_type(self, cf_type):
    """
    Get all the document by types, uses search_after

    :param self: the opensearch client's class
    :param cf_type: the contentful type
    :return:
    """
    opn_entries = opn_query_search_after(self, cf_type, 10000)
    # Create an empty list
    opn_entries_list = []
    # Continue while opensearch continues returning entries
    while len(opn_entries['hits']['hits']):
        # Get the document ID and add it to `opn_entries_list`
        for opn_entry in opn_entries['hits']['hits']:
            opn_entries_list.append(opn_entry['_id'])
        # Start a new search with search_after parameter
        opn_entries = opn_query_search_after(self, cf_type, 10000, opn_entries['hits']['hits'][-1]['sort'])
    return opn_entries_list


class OpnConnect:
    """
    Class to connect to OpenSearch
    """
    def __init__(self, opn_host, opn_port, opn_auth):
        self.opn_host = opn_host
        self.opn_port = opn_port
        self.opn_auth = opn_auth
        self.opn_connect = opn_connect(self)


class OpnClient:
    """
    Class for the OpenSearch connect client
    """
    def __init__(self, cf_env, opn_host, opn_port, opn_auth):
        self.opn_client = OpnConnect(opn_host, opn_port, opn_auth).opn_connect
        self.opn_cf_index = f"d4w-entries_{cf_env}"
        self.opn_cf_index_new = ''
