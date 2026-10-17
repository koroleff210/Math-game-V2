"""Create only game.korephysics.com with the existing Cloudflare credential."""
import argparse
import base64
import json
from pathlib import Path
import re
from urllib.request import Request, urlopen

NAME = 'game.korephysics.com'
IP = '158.69.213.70'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--create', action='store_true')
    args = parser.parse_args()
    pem = (Path.home() / '.cloudflared/cert.pem').read_text()
    credential = json.loads(base64.b64decode(re.sub(r'-----[^\n]+-----|\s', '', pem)))
    base = 'https://api.cloudflare.com/client/v4/zones/' + credential['zoneID'] + '/dns_records'
    def call(method, suffix, body=None):
        request = Request(base + suffix, method=method,
                          headers={'Authorization': 'Bearer ' + credential['apiToken'], 'Content-Type': 'application/json'},
                          data=json.dumps(body).encode() if body is not None else None)
        with urlopen(request, timeout=30) as response:
            result = json.load(response)
        if not result.get('success'):
            raise RuntimeError('DNS request failed.')
        return result['result']
    matches = call('GET', '?name=' + NAME)
    if matches and (len(matches) != 1 or matches[0]['type'] != 'A' or matches[0]['content'] != IP or matches[0]['proxied']):
        raise SystemExit('Game hostname already has a different record. No change made.')
    if not matches and args.create:
        call('POST', '', dict(type='A', name=NAME, content=IP, ttl=60, proxied=False))
        matches = call('GET', '?name=' + NAME)
    print(json.dumps([{k: row[k] for k in ('name', 'type', 'content', 'proxied')} for row in matches]))


if __name__ == '__main__':
    main()
