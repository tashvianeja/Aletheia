from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.request import Request, urlopen


def main() -> None:
    parser = argparse.ArgumentParser(description='Explicitly update the local Tracker Radar domain seed from its GitHub catalogue.')
    parser.add_argument('--output',type=Path,default=Path(__file__).resolve().parents[1]/'src/privacy_guardian/data/trackers.json')
    args = parser.parse_args()
    url = 'https://api.github.com/repos/duckduckgo/tracker-radar/git/trees/main?recursive=1'
    request = Request(url,headers={'Accept':'application/vnd.github+json','User-Agent':'PrivacyGuardian-tracker-update'})
    with urlopen(request,timeout=30) as response:
        catalogue = json.load(response)
    if catalogue.get('truncated'):
        raise RuntimeError('Upstream catalogue was truncated; existing list preserved')
    domains = sorted({item['path'].removeprefix('domains/US/').removesuffix('.json') for item in catalogue['tree']
                      if re.fullmatch(r'domains/US/[a-z0-9.-]+\.json',item['path'])})
    if len(domains)<100:
        raise RuntimeError('Upstream catalogue unexpectedly small; existing list preserved')
    data = {'source':'DuckDuckGo Tracker Radar','source_url':url,'license':'CC-BY-NC-SA-4.0',
            'copyright':'Copyright 2020 Duck Duck Go, Inc.','domains':domains}
    args.output.write_text(json.dumps(data,indent=2)+'\n')
    print(f'Updated {len(domains)} tracker domains at {args.output}')


if __name__ == '__main__':
    main()
