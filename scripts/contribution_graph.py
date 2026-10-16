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
    colors = cfg['colors']
    if len(colors) != 5 or not all(re.fullmatch(r'#[0-9a-fA-F]{6}', c) for c in colors):
        raise ValueError('colors must contain five hex colors from empty to busiest')
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
    years = list(range(start.year, end.year + 1))
    height = 100 + len(years) * 159
    total = sum(count for date, (count, _) in data.items() if start.isoformat() <= date <= end.isoformat())
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="900" height="{height}" viewBox="0 0 900 {height}" role="img" aria-labelledby="title desc">',
           '<title id="title">Contribution calendar</title>',
           f'<desc id="desc">{username}, {start} to {end}, {total:,} GitHub-reported contributions.</desc>',
           f'<rect width="900" height="{height}" rx="12" fill="#0d1117"/>',
           '<g font-family="Arial, sans-serif" fill="#c9d1d9">',
           '<text x="28" y="32" font-size="19" font-weight="600">Contribution activity</text>',
           f'<text x="28" y="55" font-size="12" fill="#8b949e">{start} — {end} · {total:,} contributions</text>']
    for index, year in enumerate(years):
        y = 89 + index * 159
        first = dt.date(year, 1, 1)
        origin = first - dt.timedelta(days=(first.weekday() + 1) % 7)
        stop = dt.date(year, 12, 31)
        yearly = sum(count for date, (count, _) in data.items() if max(start, first).isoformat() <= date <= min(end, stop).isoformat())
        svg.append(f'<text x="28" y="{y}" font-size="15" font-weight="600">{year}</text>')
        svg.append(f'<text x="850" y="{y}" text-anchor="end" font-size="12" fill="#8b949e">{yearly:,} contributions</text>')
        for month in range(1, 13):
            week = (dt.date(year, month, 1) - origin).days // 7
            svg.append(f'<text x="{58 + week * 15}" y="{y+21}" font-size="10" fill="#8b949e">{calendar.month_abbr[month]}</text>')
        for row, label in [(1, 'Mon'), (3, 'Wed'), (5, 'Fri')]:
            svg.append(f'<text x="28" y="{y+36+row*14}" font-size="9" fill="#8b949e">{label}</text>')
        date = first
        while date <= stop:
            if start <= date <= end:
                if date.isoformat() not in data:
                    raise ValueError(f'Missing contribution day: {date}')
                count, level = data[date.isoformat()]
                x = 58 + ((date - origin).days // 7) * 15
                cy = y + 27 + ((date.weekday() + 1) % 7) * 14
                svg.append(f'<rect x="{x}" y="{cy}" width="12" height="11" rx="2" fill="{colors[level]}"><title>{date}: {count} contributions</title></rect>')
            date += dt.timedelta(days=1)
    bottom = height - 22
    svg.append(f'<text x="28" y="{bottom}" font-size="10" fill="#8b949e">GitHub-reported activity · updated {today}</text>')
    svg.append(f'<text x="704" y="{bottom}" font-size="10" fill="#8b949e">Less</text>')
    for i, color in enumerate(colors):
        svg.append(f'<rect x="{734+i*15}" y="{bottom-10}" width="12" height="11" rx="2" fill="{color}"/>')
    svg.append(f'<text x="814" y="{bottom}" font-size="10" fill="#8b949e">More</text></g></svg>')
    (ROOT / 'assets/contributions.svg').write_text('\n'.join(svg))
    print(f'Rendered {len(years)} years, {total:,} contributions, {start} to {end}')

if __name__ == '__main__':
    main()
