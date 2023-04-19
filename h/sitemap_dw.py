import os
from opensearchpy import OpenSearch
from dotenv import load_dotenv

# Import Boto and deps for S3
import boto3
import logging
import sys
from botocore.exceptions import ClientError

# Import xml
from xml.etree import ElementTree as ET

load_dotenv()

# Global variable definition
opn_host = os.environ['OPN_HOST']
opn_ca = 'ca'
opn_port = os.environ['OPN_PORT']
opn_cf_index = os.environ['OPN_CF_INDEX']
s3_bucket = os.environ['S3_BUCKET']
site_url = os.environ['SITE_URL']

languages = ['de', 'en', 'fr', 'nl']

# Sitemaps definition
sitemap_categories = {
    'fr': {
        'person': 'personnes',
        'program': 'programmes',
        'post': 'publications',
        'profile': 'cartographie',
        'event': 'agenda',
        'strategy': 'strategie',
        'actionPlan': 'fiches-action'
    },
    'en': {
        'person': 'persons',
        'program': 'programs',
        'post': 'posts',
        'profile': 'cartography',
        'event': 'events',
        'strategy': 'strategy',
        'actionPlan': 'action-plans'
    }
}

xml_ns = {
    'default': 'http://www.sitemaps.org/schemas/sitemap/0.9',
    'news': 'http://www.google.com/schemas/sitemap-news/0.9',
    'xhtml': 'http://www.w3.org/1999/xhtml',
    'image': 'http://www.google.com/schemas/sitemap-image/1.1',
    'video': 'http://www.google.com/schemas/sitemap-video/1.1'
}

sitemap_url = os.environ['SITEMAP_URL']


# S3 Boto definitions
s3 = boto3.resource('s3')

# change the working directory for lambda
root_dir = '/tmp'
os.chdir(root_dir)


# Let's put some colors in this B&W world
class bcolors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'


# Connect functions
def opn_connect():
    client = OpenSearch(
        hosts=[{'host': opn_host, 'port': opn_port}],
        http_compress=True,  # enables gzip compression for request bodies
        # http_auth=opn_auth,
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


# Let's connect to the APIs globally
opn_client = opn_connect()


# Generate a urlset for the taking a list of dicts as argument
def create_urlset_xml(d, main_language, prefix):
    for k, v in xml_ns.items():
        if k == 'default':
            ET.register_namespace('', v)
        else:
            ET.register_namespace(k, v)
    lang_sitemap = ['fr', 'en']
    # Define useful variable
    changefreq_var = 'daily'
    slug_field = f"fields.slug.{main_language}"
    for item in d:
        v = item['fields']
        if f"fields.slug.{main_language}" in v:
            print(f"building sitemap for {item['_id']} with lang: {main_language}")
            id_number = 1
            for c in item['_id']:
                if c.isdigit():
                    id_number = c
            index_xml = f"{main_language}/{sitemap_categories[main_language][v['sys.contentType.sys.id'][0]]}/{id_number}/index.xml"
            tree = ET.ElementTree()
            tree.parse(index_xml)
            urlset = tree.getroot()
            slug_field = f"fields.slug.{main_language}"
            url = ET.SubElement(urlset, 'url')
            loc = ET.SubElement(url, 'loc')
            loc.text = f"{prefix}/{main_language}/{sitemap_categories[main_language][v['sys.contentType.sys.id'][0]]}/{v[slug_field][0]}/"
            lastmod = ET.SubElement(url, 'lastmod')
            if "sys.updatedAt" in v:
                cf_lastmod = v['sys.updatedAt'][0]
            else:
                cf_lastmod = v['sys.createdAt'][0]
            lastmod.text = cf_lastmod
            changefreq = ET.SubElement(url, 'changefreq')
            changefreq.text = changefreq_var
            slug_field = f"fields.slug.{main_language}"
            loc.text = f"{prefix}/{main_language}/{sitemap_categories[main_language][v['sys.contentType.sys.id'][0]]}/{v[slug_field][0]}/"
            for lang in lang_sitemap:
                if f"fields.slug.{lang}" in v:
                    slug_field = f"fields.slug.{lang}"
                    link = ET.SubElement(url, 'xhtml:link')
                    link.set('xmlns:xhtml', 'http://www.w3.org/1999/xhtml')
                    link.set('rel', 'alternate')
                    link.set('hreflang', lang)
                    link.set('href',
                             f"{prefix}/{lang}/{sitemap_categories[lang][v['sys.contentType.sys.id'][0]]}/{v[slug_field][0]}/")
            tree.write(index_xml, encoding='utf-8', xml_declaration=True)


def generate_urlset_xml():
    urlset = ET.Element('urlset')
    for prefix, uri in xml_ns.items():
        if prefix != 'default':
            urlset.set(f"xmlns:{prefix}", uri)
        else:
            urlset.set(f"xmlns", uri)
    return ET.ElementTree(urlset)


def generate_sitemap_index_xml(l, prefix=''):
    sitemapindex = ET.Element('sitemapindex')
    sitemapindex.set('xmlns', xml_ns['default'])
    for v in l:
        sitemap = ET.SubElement(sitemapindex, 'sitemap')
        sub = ET.SubElement(sitemap, 'loc')
        if prefix != '':
            new_prefix = f"/{prefix}"
        else:
            new_prefix = prefix
        sub.text = f"{sitemap_url}{new_prefix}/{v}/index.xml"
    et = ET.ElementTree(sitemapindex)
    if prefix == '':
        et.write(f"index.xml", encoding='utf-8', xml_declaration=True, method='xml')
    else:
        try:
            os.mkdir(prefix)
        except:
            print('directory already exists')
        et.write(f"{prefix}/index.xml", encoding='utf-8', xml_declaration=True, method='xml')
    return sitemapindex


def generate_skeleton():
    # Create the main sitemaps file
    lang = [k for k, v in sitemap_categories.items()]
    generate_sitemap_index_xml(lang, '')
    # For all the languages add a loc
    for l in lang:
        categories = [v for k, v in sitemap_categories[l].items()]
        generate_sitemap_index_xml(categories, f"{l}")
        urlset = generate_urlset_xml()
        for cat in categories:
            generate_sitemap_index_xml(list(range(10)), prefix=f"{l}/{cat}")
            for i in list(range(10)):
                try:
                    dir = f"{l}/{cat}/{i}"
                    os.makedirs(dir)
                except:
                    print('directory already exists')
                urlset.write(f"{l}/{cat}/{i}/index.xml", encoding='utf-8', xml_declaration=True)


def main():
    # Register the different namespaces
    for k, v in xml_ns.items():
        if k == 'default':
            ET.register_namespace('', v)
        else:
            ET.register_namespace(k, v)
    lang_sitemap = ['fr', 'en']

    generate_skeleton()
    upload_s3(s3_bucket, '/tmp/')
    number_entries = 0
    for cf_type in [k for k, v in sitemap_categories['fr'].items()]:
        entries = query_opn_inital_sitemap(cf_type, 10000)
        while len(entries['hits']['hits']):
            for language in lang_sitemap:
                create_urlset_xml(entries['hits']['hits'], language, site_url)
            print(entries['hits']['hits'][-1]['sort'])
            entries = query_opn(cf_type, 10000, entries['hits']['hits'][-1]['sort'])
            number_entries += entries['hits']['total']['value']
    print(f"build sitemaps for {number_entries} entries")
    upload_s3(s3_bucket, '/tmp/')
    print(f"pushed to s3")


def query_opn_inital_sitemap(cf_type, size):
    opn_query = {"query": { "bool":{"must": [{"term": {"sys.contentType.sys.id": cf_type}},
                    {"term": {"fields.clientSites.fr.name.fr": "Digital Wallonia"}}]}},
                 "fields": ["fields.slug.*", "sys.contentType.sys.id", "sys.updatedAt", "sys.createdAt", "sort"],
                 "_source": False, "sort": [{"fields.publishedDate.fr": "asc"}, {"_id": "desc"}], "size": size}
    opn_entries = opn_client.search(
        body=opn_query,
        index=opn_cf_index,
        # scroll='5m',
        #size=size,
        #request_timeout=120
    )
    return opn_entries


def query_opn(cf_type, size, search_after=0):
    opn_query = {"query": { "bool":{"must": [{"term": {"sys.contentType.sys.id": cf_type}},
                    {"term": {"fields.clientSites.fr.name.fr": "Digital Wallonia"}}]}},
                 "fields": ["fields.slug.*", "sys.contentType.sys.id", "sys.updatedAt", "sys.createdAt", "sort"],
                 "_source": False, "sort": [{"fields.publishedDate.fr": "asc"}, {"_id": "desc"}],
                 "search_after": search_after, "size": size}
    opn_entries = opn_client.search(
        body=opn_query,
        index=opn_cf_index,
        # search_after=search_after,
        #size=size,
        #request_timeout=120
    )
    return opn_entries


# Upload to bucket the content of local_directory
def upload_s3(bucket_name, sourceDir, destDir=''):
    for subdir, dirs, files in os.walk(sourceDir):
        for file in files:
            full_path = os.path.join(subdir, file)
            dest_path = full_path.replace(sourceDir, '')
            print(f"Uploading {full_path} to {bucket_name}/{dest_path}")
            s3.Bucket(bucket_name).upload_file(full_path, dest_path)


def lambda_handler(event, context):
    # TODO implement
    main()

