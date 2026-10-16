"""Render GitHub's publicly visible contribution calendar using README settings."""
import calendar
import datetime as dt
import html
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import urllib.request
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]

class CalendarParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.cells, self.tips = {}, {}
        self.tip_id = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get('data-date') and a.get('data-level') is not None:
            self.cells[a['id']] = (a['data-date'], int(a['data-level']))
        if tag == 'tool-tip':
            self.tip_id = a.get('for')

    def handle_data(self, data):
        if self.tip_id:
            self.tips[self.tip_id] = self.tips.get(self.tip_id, '') + data

    def handle_endtag(self, tag):
        if tag == 'tool-tip':
            self.tip_id = None

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
    data = {}
    for year in range(start.year, end.year + 1):
        last = min(end, dt.date(year, 12, 31))
        url = f'https://github.com/users/{username}/contributions?from={year}-01-01&to={last.isoformat()}'
        request = urllib.request.Request(url, headers={'User-Agent': 'GitHub-Profile-Contribution-Graph'})
        with urllib.request.urlopen(request, timeout=45) as response:
            parser = CalendarParser()
            parser.feed(response.read().decode())
        if len(parser.cells) < 28:
            raise ValueError(f'GitHub returned an incomplete calendar for {year}')
        for cell_id, (date, level) in parser.cells.items():
            tip = parser.tips.get(cell_id, '')
            count_match = re.search(r'([\d,]+) contribution', tip)
            if not count_match and 'No contributions' not in tip:
                raise ValueError(f'Missing contribution count for {date}')
            count = int(count_match.group(1).replace(',', '')) if count_match else 0
            data[date] = (count, level)
    filtered = {date: count for date, (count, _) in data.items() if start.isoformat() <= date <= end.isoformat()}
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
           '<title id="title">GitHub performance — monthly contributions</title>',
           f'<desc id="desc">Public activity for {username}, {start} through {end}. {total} contributions across {active} active days.</desc>',
           '<defs><linearGradient id="fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="'+accent+'" stop-opacity="0.30"/><stop offset="100%" stop-color="'+accent+'" stop-opacity="0.01"/></linearGradient></defs>',
           '<rect x="1" y="1" width="898" height="438" rx="14" fill="#0d1117" stroke="#272d36"/>',
           '<g font-family="Arial,sans-serif" fill="#e6edf3">',
           '<text x="30" y="36" font-size="18" font-weight="600">GitHub performance</text>',
           f'<text x="870" y="35" text-anchor="end" font-size="11" fill="#8b949e">{start.strftime("%b %Y")} — {end.strftime("%b %Y")}</text>']
    for x, label, value, sub in [(30,'CONTRIBUTIONS',f'{total:,}','public activity'),(320,'ACTIVE DAYS',str(active),'days with contributions'),(610,'PEAK MONTH',str(peak),peak_month)]:
        svg += [f'<rect x="{x}" y="60" width="260" height="84" rx="8" fill="#11161d"/>',
                f'<text x="{x+16}" y="80" font-size="10" letter-spacing="1.2" fill="#8b949e">{label}</text>',
                f'<text x="{x+16}" y="112" font-size="26" font-weight="600">{value}</text>',
                f'<text x="{x+16}" y="131" font-size="10" fill="#8b949e">{sub}</text>']
    svg.append('<text x="30" y="171" font-size="11" fill="#8b949e">Monthly contributions</text>')
    for i in range(5):
        v = top*i/4
        y = y1-(y1-y0)*i/4
        svg += [f'<path d="M{x0},{y} H{x1}" stroke="#242b34" stroke-dasharray="3 5"/>',
                f'<text x="53" y="{y+4}" text-anchor="end" font-size="10" fill="#8b949e">{int(v)}</text>']
    svg += [f'<path d="{area}" fill="url(#fill)"/>',f'<path d="{line}" fill="none" stroke="{accent}" stroke-width="2.5" stroke-linejoin="round"/>']
    for (month, value),(x,y) in zip(months,points):
        svg.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3" fill="{accent}" stroke="#0d1117" stroke-width="1"><title>{month}: {value} contributions</title></circle>')
    indices = sorted(set([0,len(months)-1]+[i for i,(m,_) in enumerate(months) if m.endswith('-01')]))
    for i in indices:
        x,_ = points[i]
        label = dt.date.fromisoformat(months[i][0]+'-01').strftime('%b %Y')
        svg.append(f'<text x="{x}" y="392" text-anchor="middle" font-size="10" fill="#8b949e">{label}</text>')
    svg.append(f'<text x="30" y="423" font-size="10" fill="#8b949e">Source: GitHub public contributions · updated {today}</text></g></svg>')
    (ROOT / 'assets/contributions.svg').write_text('\n'.join(svg))
    print(f'Rendered {len(months)} months, {total:,} public contributions, {active} active days')

if __name__ == '__main__':
    main()
