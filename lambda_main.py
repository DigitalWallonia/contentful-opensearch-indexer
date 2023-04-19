import os
import sys
import boto3
import asyncio
import h
from dotenv import load_dotenv
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


async def opn_update_entry(messages):
    """
    Update or delete an entry

    :param self: the contentful and opensearch client
    :param messages: the SQS content of the event
    :return:
    """
    cf_client = await load_classes()
    h.opn_build_categories(cf_client)
    for message in messages:
        message_json = json.loads(message['body'])
        print(f"processing entry {message_json['sys']['id']}")
        cf_doc = await h.get_contentful_asset_entry_curl(cf_client, message_json['sys']['id'])
        opn_doc = h.opn_search_by_cf_id(cf_client, message_json['sys']['id'])
        if cf_doc is not None:
            await h.index_cf_entry(cf_client, message_json['sys']['id'])
            # Check if `contentType` exists since assets do not have it for example
            if 'contentType' in cf_doc['sys'] and cf_doc['sys']['contentType']['sys']['id'] == 'category':
                # Rebuilding categorytree as a category changed
                h.opn_build_categories(cf_client)
            if opn_doc is not None and h.compare_opn_contentful_document(cf_doc, opn_doc['_source']):
                # Sends the document to SNS for updating
                h.send_to_sns_topic(json.dumps(cf_doc))
                for linked_entry in h.opn_query_all_linked_entry(cf_client, message_json['sys']['id']):
                    print(f"{linked_entry} will be updated")
                    beautiful_entry = {'sys': {'id': linked_entry}}
                    h.send_to_sns_topic(json.dumps(beautiful_entry))
        else:
            h.opn_delete_document(cf_client, message_json['sys']['id'])
            print(f"entry doesn't exist in the CDA, deleted {message_json['sys']['id']}")
    await cf_client.request_client.close()


# Defining entry functionc
def lambda_handler(event, lambda_context):
    """
    Loads the event from SQS into the lambda and update the entries
    :param event: the lambda event
    :param lambda_context: ignored here
    :return:
    """
    asyncio.run(opn_update_entry(event['Records']))


async def load_classes():
    """
    Loads the classes we will need throughout
    :return: `cf_client` the contentful client
    """
    aws_client_session = boto3.session.Session()
    aws_client = aws_client_session.client(
        service_name='secretsmanager',
        region_name=os.environ['AWS_REGION']
    )
    get_secret_value_response = aws_client.get_secret_value(
        SecretId=os.environ['SECRET_NAME']
    )
    secret_string = json.loads(get_secret_value_response['SecretString'])
    opn_auth = (os.environ['OPN_USERNAME'], secret_string['OPN_PASSWORD'])
    opn_client = h.OpnClient(cf_env, opn_host, opn_port, opn_auth)
    cf_client = h.ContentfulClient(cf_client_id, secret_string['CF_DELIVERY_TOKEN'], cf_env, opn_client.opn_client)
    return cf_client
