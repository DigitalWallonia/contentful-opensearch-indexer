import json
f = open('/home/vinz/Open Search DW.postman_collection.json')
data = json.load(f)
f.close()

for item in data['item'][0]['item']:
    oi = item
    if '_doc' in item['request']['url']['path']:
        name = item['request']['url']['path'][2]
        body = item['request']['body']['raw']
        f = open(f"shape-wallonia/{name}", "a")
        f.write(body)
        f.close()

for item in data['item'][0]['item']:
    oi = item
    if '_scripts' in item['request']['url']['path']:
        name = item['request']['url']['path'][1]
        body = item['request']['body']['raw']
        f = open(f"template-opensearch/{name}", "a")
        f.write(body)
        f.close()
    #print(item)
