import os
import sys
import datetime
import asyncio
import time
import h
from dotenv import load_dotenv
import mapping_dw_es_var
import tracemalloc
import json

load_dotenv()

cf_delivery_token = os.environ['CF_DELIVERY_TOKEN']
opn_host = os.environ['OPN_HOST']
opn_port = os.environ['OPN_PORT']
opn_auth = (os.environ['OPN_USERNAME'], os.environ['OPN_PASSWORD'])
cf_env = os.environ['CF_ENV']
cf_client_id = os.environ['CF_CLIENT_ID']

# asyncio variables
background_tasks = set()
concurrent_entries = 0


async def check_all_cf_entries_by_types(self, cf_type, no_cache=False, create_tasks=False):
    """
    Requests all entries for a Contentful type matching a pattern ``cf_type`` in Contentful and Opensearch
    Sends it down to the :func: `check_indexation` function which compares the result and index if needed

    the pattern used is defined in ``mapping_dw_es_var.py``

    args:
        ``cf_type``: the contentType from contentful
    """
    # Used for paginating results
    cf_limit = 1000
    skip_parameter = 0
    # Settings for the requests
    template_p = {'content_type': cf_type, 'select': 'sys.id',
                'limit': cf_limit, 'skip': skip_parameter}
    template_p.update(mapping_dw_es_var.cf_param[cf_type])
    # Get all af the opensearch's entries, create a list of all the ID
    if no_cache:
        opn_entries_list = []
    else:
        opn_entries_list = h.opn_get_all_document_id_from_type(self, cf_type)
    # If `no_cache` True then return an empty list to force indexation
    # While we are getting entries paginate to the next ``cf_limit``
    cf_entries = ['something']
    while len(cf_entries) > 0:
        # Get all af the entries ``cf_limit`` at the time
        template_str = ''
        # Convert ``template_p`` which is a :dict: to :string:
        for key, value in template_p.items():
            template_str += f"&{key}={value}"
        cf_entries = await h.get_contentful_asset_entry_curl(self, param=template_str, return_first=False, cf_link_type='Entry')
        # Check the indexation status of the entries previously returned
        await check_indexation(self, cf_entries, opn_entries_list, create_tasks=no_cache)
        # If we get less entries than the ``cf_limit`` we have reached the last ones, exits
        skip_parameter += cf_limit
        template_p['skip'] += cf_limit
    while len(background_tasks) > 0:
        await asyncio.sleep(5)


async def check_indexation(self, cf_entries, opn_entries, create_tasks=False):
    """
    Checks if the ``cf_entry`` exists in Opensearch.
    if it doesn't, imports it using
        * :func: `get_contentful_asset_entry_curl` which gets the plain entry from the CDA
        * :func: `dict_resolve_links` which resolved all links from the entry
    else does nothing

    args:
        ``cf_entries``: The list of contentful entries
        ``opn_entries``: The list of opensearch entries
    """
    # Iterates over the list of entries and check if it exists in opensearch, if not imports it
    for cf_entry in cf_entries:
        # If you want to reimport all entries regardless of it existence in Opensearch
        # uncomment the following line
        #opn_entries = []
        # If the opensearch response is `None` this means the entry doesn't exist in opensearch
        if cf_entry['sys']['id'] not in opn_entries:
            print(f"{h.bcolors.OKCYAN}Entry {cf_entry['sys']['id']} not yet indexed, indexing")
            # Adds the contentful entry ID to prevent recursion in the linked entries resolution
            global cf_current_id
            cf_current_id = cf_entry['sys']['id']
            if create_tasks:
                await h.index_cf_entry(self, cf_entry['sys']['id'])
            else:
                task = asyncio.ensure_future(h.index_cf_entry(self, cf_entry['sys']['id']))
                # Add task to the set. This creates a strong reference.
                background_tasks.add(task)
                # To prevent keeping references to finished tasks forever,
                # make each task remove its own reference from the set after
                # completion:
                task.add_done_callback(background_tasks.discard)
        else:
            print(f"{h.bcolors.OKGREEN}Entry {cf_entry['sys']['id']} already indexed")


async def main():
    tracemalloc.start()
    opn_client = h.OpnClient(cf_env, opn_host, opn_port, opn_auth)
    cf_client = h.ContentfulClient(cf_client_id, cf_delivery_token, cf_env, opn_client.opn_client)
    full_index = True
    if full_index is True:
        # Generate a new index with a mmddyyyy format
        opn_client.opn_cf_index = f"d4w-entries_{cf_env}-{datetime.datetime.now().strftime('%m%d%Y')}"
        cf_client.opn_cf_index = opn_client.opn_cf_index
    h.opn_update_mapping(opn_client)
    h.opn_update_search_template(opn_client)
    h.opn_put_shape_template(opn_client)
    #await h.index_cf_entry(cf_client, '3zpOKXhalGUKaNznOKCTjl')
    await check_all_cf_entries_by_types(cf_client, 'category', create_tasks=True)
    # Set back the opensearch cache
    h.set_no_cache(False)
    h.opn_build_categories(opn_client)
    for cf_type, v in mapping_dw_es_var.cf_param.items():
        await check_all_cf_entries_by_types(cf_client, cf_type)
    print(f'{h.bcolors.FAIL}The following entries could not be indexed {cf_client.unavailable_cf_entry}')
    # Close the rate limit file opened in the class definition
    cf_client.rate_limit_file.close()
    # Make the alias point to the newly created index and remove the old one
    aliases = opn_client.opn_client.indices.get_alias(f"d4w-entries_{cf_env}")
    for key, value in aliases.items():
        print(f"{h.bcolors.OKCYAN}Notice: removing {key} from alias d4w-entries_{cf_env}")
        h.opn_manage_aliases(opn_client, f"d4w-entries_{cf_env}", key, 'remove')
    h.opn_manage_aliases(opn_client, f"d4w-entries_{cf_env}", opn_client.opn_cf_index_new)
    tracemalloc.stop()
    await cf_client.request_client.close()
    print(tracemalloc.get_traced_memory())


start_time = time.time()
asyncio.run(main())
print("--- %s seconds ---" % (time.time() - start_time))
