import urllib.request, json, urllib.error
req = urllib.request.Request(
    'https://backend-f470913f.fastapicloud.dev/chat/query',
    method='POST',
    headers={'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'},
    data=json.dumps({'question': 'Hello'}).encode('utf-8')
)
try:
    response = urllib.request.urlopen(req)
except urllib.error.HTTPError as e:
    with open('error_out.txt', 'w', encoding='utf-8') as f:
        f.write(f'HTTP Error {e.code}: {e.read().decode("utf-8")}')
except Exception as e:
    with open('error_out.txt', 'w', encoding='utf-8') as f:
        f.write(f'Error: {e}')