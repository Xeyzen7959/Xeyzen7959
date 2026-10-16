"""Render GitHub's publicly visible contribution calendar using README settings."""
import datetime as dt
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.request
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]

def api_token():
    token = os.environ.get('GH_STATS_TOKEN') or os.environ.get('GITHUB_TOKEN')
    if token:
        return token
    # Reuse existing local Git authentication; never log or store credentials.
    result = subprocess.run(['git', 'credential', 'fill'], input='protocol=https\nhost=github.com\n\n', text=True, capture_output=True, check=True)
    fields = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    if not fields.get('password'):
        raise ValueError('GitHub authentication is required')
    return fields['password']

def fetch_commits(username, start, end, include_private):
    token = api_token()
    public, private = {}, {}
    for year in range(start.year, end.year + 1):
        aliases = []
        for month in range(1, 13):
            first = dt.date(year, month, 1)
            next_month = (first.replace(day=28)+dt.timedelta(days=4)).replace(day=1)
            last = next_month-dt.timedelta(days=1)
            if first > end or last < start:
                continue
            lo, hi = max(first,start), min(last,end)
            aliases.append(f'm{month}: contributionsCollection(from:"{lo}T00:00:00Z",to:"{hi}T23:59:59Z") {{ commitContributionsByRepository(maxRepositories:100) {{ repository {{ isPrivate }} contributions(first:100) {{ nodes {{ occurredAt commitCount }} pageInfo {{ hasNextPage }} }} }} }}')
        query = 'query($login:String!) { user(login:$login) { '+ ' '.join(aliases)+' } }'
        request = urllib.request.Request('https://api.github.com/graphql',data=json.dumps({'query':query,'variables':{'login':username}}).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json','User-Agent':'Profile-Commit-Chart'})
        with urllib.request.urlopen(request,timeout=60) as response:
            result=json.load(response)
        if result.get('errors'):
            raise ValueError('GitHub GraphQL query failed: '+str([e.get('message') for e in result['errors']]))
        if not result.get('data',{}).get('user'):
            raise ValueError('GitHub user was not found')
        for collection in result['data']['user'].values():
            repositories=collection['commitContributionsByRepository']
            if len(repositories)==100:
                raise ValueError('Repository limit reached; refusing to publish incomplete counts')
            for repo in repositories:
                if repo['contributions']['pageInfo']['hasNextPage']:
                    raise ValueError('Contribution page limit reached')
                target = private if repo['repository']['isPrivate'] else public
                for node in repo['contributions']['nodes']:
                    day=node['occurredAt'][:10]
                    target[day]=target.get(day,0)+node['commitCount']
    snapshot_path=ROOT/'assets/private-commit-counts.json'
    if include_private:
        capture = os.environ.get('CAPTURE_PRIVATE')=='1' or bool(os.environ.get('GH_STATS_TOKEN'))
        if capture:
            snapshot_path.write_text(json.dumps({'username':username,'through':end.isoformat(),'counts':private},indent=2,sort_keys=True)+'\n')
        elif snapshot_path.exists():
            snapshot=json.loads(snapshot_path.read_text())
            if snapshot['username']==username:
                for day,count in snapshot['counts'].items():
                    private[day]=max(private.get(day,0),count)
        for day,count in private.items():
            public[day]=public.get(day,0)+count
    return public

def main():
    readme = (ROOT / 'README.md').read_text()
    match = re.search(r'<!-- contribution-graph-config\s*(.*?)\s*-->', readme, re.S)
    if not match:
        raise ValueError('Missing contribution-graph-config in README.md')
    cfg = json.loads(match.group(1))
    username = cfg['username']
    if not re.fullmatch(r'[A-Za-z0-9-]{1,39}', username):
        raise ValueError('Invalid GitHub username')
    today = dt.datetime.now(ZoneInfo('Asia/Jakarta')).date()
    start = dt.date.fromisoformat(cfg['start'])
    end = today if cfg['end'] == 'today' else min(today, dt.date.fromisoformat(cfg['end']))
    if not dt.date(2008, 1, 1) <= start <= end:
        raise ValueError('Date range must start in 2008 or later and end after its start')
    accent = cfg.get('accent', '#ef4444')
    if not re.fullmatch(r'#[0-9a-fA-F]{6}', accent):
        raise ValueError('accent must be a hex color')
    include_private = cfg.get('includePrivate', False)
    filtered = fetch_commits(username, start, end, include_private)
    filtered = {day: count for day,count in filtered.items() if start.isoformat() <= day <= end.isoformat()}
    scope = 'public + private' if include_private else 'public commits'
    total = sum(filtered.values())
    active = sum(count > 0 for count in filtered.values())
    months = []
    current = start.replace(day=1)
    while current <= end:
        prefix = current.strftime('%Y-%m')
        months.append((prefix, sum(v for d, v in filtered.items() if d.startswith(prefix))))
        current = (current.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    peak_month, peak = max(months, key=lambda m: m[1])
    top = max(4, ((peak + 3) // 4) * 4)
    x0, x1, y0, y1 = 65, 855, 187, 369
    points = [(x0 + i*(x1-x0)/max(1,len(months)-1), y1-v/top*(y1-y0)) for i,(_,v) in enumerate(months)]
    line = ' '.join(('M' if i==0 else 'L')+f'{x:.2f},{y:.2f}' for i,(x,y) in enumerate(points))
    area = line + f' L{x1},{y1} L{x0},{y1} Z'
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="900" height="440" viewBox="0 0 900 440" role="img" aria-labelledby="title desc">',
           '<title id="title">GitHub performance — monthly commits</title>',
           f'<desc id="desc">Commit activity for {username}, {start} through {end}. {total} commits across {active} active days.</desc>',
           '<defs><linearGradient id="fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="'+accent+'" stop-opacity="0.30"/><stop offset="100%" stop-color="'+accent+'" stop-opacity="0.01"/></linearGradient></defs>',
           '<rect x="1" y="1" width="898" height="438" rx="14" fill="#0d1117" stroke="#272d36"/>',
           '<g font-family="Arial,sans-serif" fill="#e6edf3">',
           f'<text x="870" y="35" text-anchor="end" font-size="11" fill="#8b949e">{start.strftime("%b %Y")} — {end.strftime("%b %Y")}</text>']
    for x, label, value, sub in [(30,'COMMITS',f'{total:,}',scope),(320,'ACTIVE DAYS',str(active),'days with commits'),(610,'PEAK MONTH',str(peak),peak_month)]:
        svg += [f'<rect x="{x}" y="60" width="260" height="84" rx="8" fill="#11161d"/>',
                f'<text x="{x+16}" y="80" font-size="10" letter-spacing="1.2" fill="#8b949e">{label}</text>',
                f'<text x="{x+16}" y="112" font-size="26" font-weight="600">{value}</text>',
                f'<text x="{x+16}" y="131" font-size="10" fill="#8b949e">{sub}</text>']
    svg.append('<text x="30" y="171" font-size="11" fill="#8b949e">Monthly commits</text>')
    for i in range(5):
        v = top*i/4
        y = y1-(y1-y0)*i/4
        svg += [f'<path d="M{x0},{y} H{x1}" stroke="#242b34" stroke-dasharray="3 5"/>',
                f'<text x="53" y="{y+4}" text-anchor="end" font-size="10" fill="#8b949e">{int(v)}</text>']
    svg += [f'<path d="{area}" fill="url(#fill)"/>',f'<path d="{line}" fill="none" stroke="{accent}" stroke-width="2.5" stroke-linejoin="round"/>']
    for (month, value),(x,y) in zip(months,points):
        svg.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3" fill="{accent}" stroke="#0d1117" stroke-width="1"><title>{month}: {value} commits</title></circle>')
    indices = sorted(set([0,len(months)-1]+[i for i,(m,_) in enumerate(months) if m.endswith('-01')]))
    for i in indices:
        x,_ = points[i]
        label = dt.date.fromisoformat(months[i][0]+'-01').strftime('%b %Y')
        svg.append(f'<text x="{x}" y="392" text-anchor="middle" font-size="10" fill="#8b949e">{label}</text>')
    svg.append(f'<text x="30" y="423" font-size="10" fill="#8b949e">Source: GitHub commit contributions · updated {today}</text></g></svg>')
    (ROOT / 'assets/commit-performance.svg').write_text('\n'.join(svg))
    print(f'Rendered {len(months)} months, {total:,} commits, {active} active days')

if __name__ == '__main__':
    main()
