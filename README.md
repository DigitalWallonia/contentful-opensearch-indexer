# contentful-opensearch-indexer

Indexes every entries matching the pattern defined in `mapping_dw_es_var.py` _see bellow for more details_ to an OpenSearch index using contentful [Content Delivery API](https://www.contentful.com/developers/docs/references/content-delivery-api/). 

The result is the same output of the Contentful Delivery API with a few changes:
* it resolves 1 level of link: `id`, `slug` and `title` if they exist (a few exceptions exists as we sometimes need 2-3 levels)
* it converts [contentful's rich text](https://www.contentful.com/developers/docs/concepts/rich-text/) to HTML. For more informations on the classes use, either refer to the code `h/richttext_convertor_dw.py`, or to the [documentation](https://github.com/DigitalWallonia/d4w-documentation/blob/main/readme.md).
* it converts contentful's rich text to plain text


## Reasons why we built it
[Contentful](https://www.contentful.com) is a headless CMS that we use to manage our website. We needed a way to do full-text search on our entries and since they had [links](https://www.contentful.com/developers/docs/concepts/links/) in them, we needed a way to resolve those links, hence this middleware saw the light of day.

We used it to convert [contentful's rich text](https://www.contentful.com/developers/docs/concepts/rich-text/) to HTML as well

 
## 🚨 Disclaimer 🚨
Please note that this project has been developed for the need of [digitalwallonia.be](https://digitalwallonia.be) and is therefore heavily customized to fit our needs

You may prefer to have a look at the headers `h/*` instead of using it directly 

## Structure

* `h`: headers
  * `aws_dw.py`: aws specific functions we use
  * `colours.py`: defines some colours class 🦄
  * `contentful_dw.py`: functions and classes used to interact with contentful
  * `opensearch_dw.py`: functions and classes used to interact with opensearch
  * `richttext_convertor_dw.py`: functions and classes used to convert richtext to HTML
  * `sitemap_dw.py`: functions and classes used to build the sitemap _as and exception to the header rule, this file is standalone_
* `lambda_main.py`: the main function we used to index contentful entries to opensearch, it runs on [AWS Lambda](https://aws.amazon.com/lambda/) but can be ran elsewhere
* `mapping_dw_es_var.py`: config file defining the [rules](https://www.contentful.com/developers/docs/references/content-delivery-api/#/introduction/common-resource-attributes) to index entries, it is a map of the desired properties
* `mapping_opensearch.json`: contains the opensearch mapping definition (see below for more informations)
* `shape-wallonia`: contains basic elasticsearch Wallonia regions' shapes
* `template-opensearch`: contains all the Opensearch templates we use

## Configs
All of the configurations parameters are environment variables:

* `CF_DELIVERY_TOKEN`: Contentful CDA API Token
* `OPN_HOST`: The Opensearch Host
* `OPN_PORT`: The Opensearch port
* `OPN_USERNAME`: The Opensearch Username
* `OPN_PASSWORD`: The Opensearch Password
* `CF_ENV`: The contentful environment
* `CF_CLIENT_ID`: A relica no longer used, we separate our fronts via a `clientSites` key
* `AWS_REGION`: The AWS Region
* `SECRET_NAME`: The AWS Secret name containing the key (for the lambda function `lambda_main.py`):
  * `OPN_PASSWORD`: same as above, used for the lambda function
  * `CF_DELIVERY_TOKEN`: same as above used by the lambda function

### `h.sitemap_dw.py`
This is the code that we use to generate our sitemap.

Unfortunately a parameter has been for the moment hardcoded on line 231, change the `fields.clientSites.fr.name.fr` to your `clientSites` to use it. It should e shared in the next future.
```python
229 def query_opn_inital_sitemap(cf_type, size): > Missing function or method docstring
230     opn_query = {"query": { "bool":{"must": [{"term": {"sys.contentType.sys.id": cf_type}},
231                     {"term": {"fields.clientSites.fr.name.fr": "Digital Wallonia"}}]}},
232                  "fields": ["fields.slug.*", "sys.contentType.sys.id", "sys.updatedAt", "sys.createdAt", "sort"],
```

`configuration`:
* `OPN_HOST`: the opensearch host url
* `OPN_PORT`: the opensearch port
* `OPN_CF_INDEX`: The opensearch index we want to use
* `S3_BUCKET`: the S3 bucket you want to update your sitemap to
* `SITE_URL`: the website root url without ending `/`
* `SITEMAP_URL`: the sitemap root url without ending `/`
### mapping_dw_es_var.py
This files defines the conditions for an entry to be indexed into Opensearch.

It is a [python dictionary](https://docs.python.org/3/tutorial/datastructures.html#dictionaries). Formatted in the following way:

```python
{
  # https://www.contentful.com/developers/docs/concepts/data-model/
  'contentType': {
    # Example of a condition for the indexation, uses the same format as the CDA
    # See for more infos https://www.contentful.com/developers/docs/references/content-delivery-api/#/reference/content-tags/querying-content-based-on-one-or-more-tags
    'fields.publishedDate[exists]': 'true'
  }
}
```

### `main.py.py`
This is our main function that we use to run the initial import.

### `mapping_opensearch.json`
The [Opensearch Mapping](https://opensearch.org/docs/latest/field-types/mappings/), with a few twists.

We added the key `localization`, since we support multiple languages (`de`, `en`, `fr`, `nl`), automatically expand it for us (you can find the code in the function `opn_generate_mappings`)

For example:
```json
{
  "slug": {
    "localization": "keyword"
  }
}
```
expands to
```json
{
  "slug" : {
    "properties" : {
      "de" : {
        "type" : "keyword"
      },
      "en" : {
        "type" : "keyword"
      },
      "fr" : {
        "type" : "keyword"
      },
      "nl" : {
        "type" : "keyword"
      }
    }
  }
}
```

### `lambda_main.py`
Used to run the incremental sync using [Contentful's webhook](https://www.contentful.com/developers/docs/concepts/webhooks/) that are send to a SQS queue.

Since Contentful doesn't support cascading changes, if an entry `slug` or `title` changes, then all entries linked will be send to an SNS topic that will be then sent to the same lambda for indexation

## Contributing
You are free to fork, contribute or do anything with this project (see license).

If you want to contribute feel free to open an issue with or without a PR.

## License
BSD 3-Clause License
