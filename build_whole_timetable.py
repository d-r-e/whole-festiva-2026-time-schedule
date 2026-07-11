#!/usr/bin/env python3
"""Build a standalone WHOLE 2026 timetable from lineup.txt."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path


EVENT_RE = re.compile(r"^(Friday|Saturday|Sunday|Monday), (\d{2}:\d{2}), (.+)$")
DAY_ORDER = ["Friday", "Saturday", "Sunday", "Monday"]


def load_artist_metadata(path: Path) -> dict[str, dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return {row["artist"]: row for row in csv.DictReader(handle)}


def load_end_times(path: Path) -> dict[tuple[str, str, str, str], str]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as handle:
        return {
            (row["day"], row["start_time"], row["stage"], row["artist"]): row["end_time"]
            for row in csv.DictReader(handle)
        }


def load_events(
    path: Path, metadata: dict[str, dict[str, str]], end_times: dict[tuple[str, str, str, str], str]
) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    block: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line == "View":
            if block:
                match = next((EVENT_RE.match(item) for item in block if EVENT_RE.match(item)), None)
                if match:
                    day, time, stage = match.groups()
                    artist = block[0]
                    category = next((item for item in block[1:] if item.startswith(("Artist", "Performer", "Collective"))), "")
                    group_match = re.match(r"^(?:Artist|Performer), (.+)$", category)
                    collective = group_match.group(1) if group_match else ""
                    is_collective = category in {"Collective", "Performer Collective"}
                    artist_data = metadata.get(artist, {})
                    related_links = [url for url in artist_data.get("wholefestival_links", "").split(";") if url]
                    soundcloud_url = artist_data.get("soundcloud_canonical_url") or artist_data.get("soundcloud_url", "")
                    if soundcloud_url and soundcloud_url not in related_links:
                        related_links.insert(0, soundcloud_url)
                    events.append({
                        "artist": artist, "day": day, "time": time, "stage": stage,
                        "end": end_times.get((day, time, stage, artist), ""),
                        "collective": collective,
                        "is_collective": is_collective,
                        "description": artist_data.get("wholefestival_description") or artist_data.get("soundcloud_description", ""),
                        "genres": artist_data.get("genres", ""),
                        "avatar": artist_data.get("soundcloud_avatar_url", ""),
                        "followers": artist_data.get("soundcloud_followers", ""),
                        "links": related_links,
                    })
            block = []
        elif line:
            block.append(line)
    return events


TEMPLATE = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>WHOLE 2026 — My timetable</title>
  <link rel="icon" href="favicon.ico" type="image/x-icon">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=DM+Sans:opsz,wght@9..40,400;9..40,500;9..40,600;9..40,700&family=Space+Grotesk:wght@500;600;700&display=swap" rel="stylesheet">
  <style>
    :root { --bg:#101312; --surface:#19211d; --surface-2:#222c25; --line:#3a493e; --text:#eef5ef; --muted:#9ca9a0; --accent:#c6ff62; --accent-dark:#172100; --glow:#1a2a20; --heat-hue:88; }
    * { box-sizing:border-box; } body { margin:0; background:linear-gradient(130deg,#0e1310,var(--glow)); color:var(--text); font:15px/1.35 "DM Sans",system-ui,sans-serif; }
    main { max-width:1800px; margin:auto; padding:14px 14px 28px; } h1 { margin:0; font:600 clamp(28px,6vw,44px)/.95 "Space Grotesk",sans-serif; letter-spacing:-.07em; } .lead { margin:4px 0 12px; color:var(--muted); font-size:13px; }
    .top { display:flex; gap:10px; align-items:flex-start; flex-direction:column; }
    .controls { display:flex; gap:5px; flex-wrap:wrap; align-items:center; width:100%; } button,select,.artist-shortcut { min-height:38px; font:600 13px/1 "DM Sans",sans-serif; color:var(--text); background:transparent; border:0; border-radius:7px; padding:8px 10px; cursor:pointer; } button:hover,select:hover,.artist-shortcut:hover { background:rgba(255,255,255,.08); } button.active { background:var(--accent); color:var(--accent-dark); font-weight:700; } .artist-shortcut { color:var(--accent); text-decoration:none; padding-left:0; } .palette { color:var(--muted); font-size:12px; } .palette select { min-height:34px; margin-left:3px; padding:6px 7px; background:var(--surface); }
    .days { display:flex; gap:4px; flex-wrap:wrap; margin:0 0 10px; } .days button { min-width:76px; }
    .selection { background:rgba(25,33,29,.72); border-radius:10px; padding:9px 11px; margin:0 0 10px; } .selection-head { display:flex; justify-content:space-between; align-items:center; gap:10px; } .selection h2 { margin:0; font:600 14px/1 "Space Grotesk",sans-serif; } #picks { display:flex; gap:5px; overflow:auto; padding-top:6px; } .pick { min-height:30px; white-space:nowrap; padding:5px 7px; background:var(--surface-2); border-radius:6px; color:#dfe9e0; font-size:12px; } .pick small { color:var(--muted); margin-right:4px; }
    .schedule-wrap { overflow:auto; border-radius:10px; background:rgba(16,19,18,.72); box-shadow:inset 0 0 0 1px rgba(255,255,255,.045); max-height:76vh; }
    .schedule { display:grid; grid-template-columns:56px repeat(var(--stages), minmax(116px,1fr)); min-width:calc(56px + var(--stages) * 116px); grid-template-rows:46px repeat(144, 11px); position:relative; }
    .stage { grid-row:1; position:sticky; top:0; z-index:5; padding:10px 8px; background:#202a22; border-right:1px solid rgba(255,255,255,.06); color:var(--accent); font:600 11px/1 "Space Grotesk",sans-serif; text-transform:uppercase; letter-spacing:.07em; }
    .time-head { grid-column:1; grid-row:1; position:sticky; top:0; z-index:6; background:#202a22; border-right:1px solid rgba(255,255,255,.06); }
    .hour { grid-column:1; color:var(--muted); border-right:1px solid var(--line); border-top:1px solid rgba(58,73,62,.55); padding:1px 7px; font-size:11px; z-index:2; }
    .line { grid-column:2 / -1; border-top:1px solid rgba(58,73,62,.4); pointer-events:none; }
    .stage-bg { grid-row:2 / -1; border-right:1px solid rgba(58,73,62,.5); }
    .event { z-index:3; margin:2px 3px; min-height:27px; display:flex; overflow:hidden; background:#27332b; border:0; border-radius:6px; box-shadow:inset 0 0 0 1px rgba(255,255,255,.05); } .event:hover { background:#324035; }
    .event.has-listeners { --heat-background:hsl(var(--heat-hue) var(--heat-saturation) var(--heat-light)); background:var(--heat-background); border-color:hsl(var(--heat-hue) var(--heat-saturation) calc(var(--heat-light) + 12%)); color:#fff; } .event.has-listeners:hover { filter:brightness(1.12); } @supports (color:contrast-color(red)) { .event.has-listeners,.event.has-listeners .event-star { color:contrast-color(var(--heat-background)); } }
    .event-card { flex:1; min-width:0; padding:5px 5px 5px 3px; color:inherit; background:transparent; border:0; border-radius:0; text-align:left; font:inherit; cursor:pointer; } .event-card:hover { border:0; }
    .event-star { width:27px; flex:0 0 27px; padding:4px 0; color:var(--muted); background:transparent; border:0; border-radius:0; font-size:15px; cursor:pointer; } .event-star:hover { color:var(--accent); border:0; }
    .event.selected { background:var(--accent); color:var(--accent-dark); box-shadow:none; font-weight:700; } .event.selected .event-star { color:var(--accent-dark); }
    .event.group-member { margin-right:30px; } .collective-rail { z-index:4; width:25px; justify-self:end; align-self:stretch; margin:2px 2px; padding:4px 3px; color:var(--accent); background:rgba(8,12,10,.88); border:0; border-left:2px solid var(--accent); border-radius:0 5px 5px 0; font:600 10px/1 "Space Grotesk",sans-serif; letter-spacing:.04em; text-transform:uppercase; cursor:pointer; writing-mode:vertical-rl; overflow:hidden; text-overflow:ellipsis; } .collective-rail:hover { color:var(--accent-dark); background:var(--accent); }
    .event .name { display:block; overflow:hidden; text-overflow:ellipsis; white-space:normal; }
    .event.hidden { display:none; } .empty { padding:45px 15px; color:var(--muted); text-align:center; }
    dialog { width:min(620px,calc(100vw - 24px)); max-height:min(720px,calc(100vh - 24px)); padding:0; overflow:auto; color:var(--text); background:#172019; border:0; border-radius:14px; box-shadow:0 28px 80px #000a; } dialog::backdrop { background:#071008b8; backdrop-filter:blur(4px); }
    .detail { padding:20px; } .detail-close { float:right; width:34px; height:34px; padding:0; border-radius:50%; font-size:20px; } .detail-head { display:flex; gap:14px; align-items:center; padding-right:42px; } .detail-avatar { width:72px; height:72px; flex:0 0 72px; object-fit:cover; border-radius:12px; background:#28342b; } .detail-avatar.fallback { display:grid; place-items:center; color:var(--accent); font-size:30px; font-weight:800; }
    .detail h2 { margin:0; font-size:clamp(25px,5vw,36px); line-height:1; letter-spacing:-.045em; } .detail-meta { margin:7px 0 0; color:var(--muted); } .detail-body { margin:18px 0; color:#dce6df; white-space:pre-line; } .detail-tags,.detail-links { display:flex; flex-wrap:wrap; gap:7px; } .detail-tag,.detail-link { padding:6px 9px; border:1px solid #46574a; border-radius:999px; color:#d9e5da; font-size:12px; text-decoration:none; } .detail-link:hover { color:#172100; background:var(--accent); border-color:var(--accent); } .detail-star { margin-top:18px; background:var(--accent); color:var(--accent-dark); border-color:var(--accent); font-weight:800; }
    body.embedded main { padding-top:12px; } body.embedded .top > div:first-child { display:none; } body.embedded .top { justify-content:flex-end; }
    @media (max-width:650px) { .selection { position:sticky; top:8px; z-index:10; box-shadow:0 7px 20px #0006; } .schedule-wrap { max-height:68vh; } .event { font-size:12px; } }
    @media (min-width:700px) { main { padding:20px clamp(22px,3vw,36px) 36px; } .top { flex-direction:row; justify-content:space-between; } .controls { width:auto; } .schedule { grid-template-columns:64px repeat(var(--stages), minmax(138px,1fr)); min-width:calc(64px + var(--stages) * 138px); } }
  </style>
</head>
<body><main>
  <div class="top"><div><h1>WHOLE 2026 timetable</h1><p class="lead">Tap an artist for details. Use the star to build your own schedule.</p></div><div class="controls"><a class="artist-shortcut" href="whole_soundcloud_standalone.html">Artists ↗</a><label class="palette">Palette <select id="palette" aria-label="Colour palette"><option value="acid">Acid</option><option value="ocean">Ocean</option><option value="sunset">Sunset</option><option value="violet">Violet</option></select></label><button id="only-picks" aria-pressed="false">Show my picks only</button><button id="clear">Clear picks</button></div></div>
  <nav id="days" class="days" aria-label="Festival day"></nav>
  <section class="selection"><div class="selection-head"><h2 id="pick-title">My schedule · 0 artists</h2><span id="pick-help" class="lead">No conflicts detected</span></div><div id="picks"><span class="muted">Pick artists from the timetable below.</span></div></section>
  <section id="timetable" class="schedule-wrap" aria-label="Festival schedule"></section>
  <dialog id="detail"><div class="detail"><button id="detail-close" class="detail-close" aria-label="Close artist details">×</button><div id="detail-content"></div></div></dialog>
</main>
<script>
if (new URLSearchParams(location.search).has('embed')) document.body.classList.add('embedded');
const events = __SCHEDULE_DATA__;
const days = ["Friday","Saturday","Sunday","Monday"];
const key = 'whole-2026-custom-schedule';
const paletteKey = 'whole-2026-palette';
const palettes = { acid:{accent:'#c6ff62',dark:'#172100',glow:'#1a2a20',hue:88}, ocean:{accent:'#6edbff',dark:'#002333',glow:'#102838',hue:197}, sunset:{accent:'#ffb56b',dark:'#351500',glow:'#322016',hue:27}, violet:{accent:'#d7a5ff',dark:'#29103b',glow:'#271c35',hue:278} };
let day = days.find(d => events.some(e => e.day === d)) || days[0];
let selected = new Set(JSON.parse(localStorage.getItem(key) || '[]'));
let picksOnly = false;
const $ = id => document.getElementById(id);
const idFor = e => `${e.day}|${e.time}|${e.stage}|${e.artist}`;
const minutes = time => { const [h,m] = time.split(':').map(Number); return h * 60 + m; };
const endMinutes = e => { const start=minutes(e.time); if (!e.end) return start+40; const end=minutes(e.end); return end<=start ? end+1440 : end; };
const escape = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function save() { localStorage.setItem(key, JSON.stringify([...selected])); }
function applyPalette(name) { const palette=palettes[name]||palettes.acid; const root=document.documentElement.style; root.setProperty('--accent',palette.accent); root.setProperty('--accent-dark',palette.dark); root.setProperty('--glow',palette.glow); root.setProperty('--heat-hue',palette.hue); $('palette').value=name; localStorage.setItem(paletteKey,name); }
function selectedEvents() { return events.filter(e => selected.has(idFor(e))).sort((a,b) => days.indexOf(a.day)-days.indexOf(b.day) || minutes(a.time)-minutes(b.time)); }
function renderDays() { $('days').innerHTML = days.filter(d=>events.some(e=>e.day===d)).map(d=>`<button class="${d===day?'active':''}" data-day="${d}">${d}</button>`).join(''); $('days').querySelectorAll('button').forEach(b=>b.onclick=()=>{day=b.dataset.day; render();}); }
function renderPicks() { const picked = selectedEvents(); $('pick-title').textContent=`My schedule · ${picked.length} artist${picked.length===1?'':'s'}`; const conflicts = picked.filter((e,i,a)=>a.some((x,j)=>j!==i && x.day===e.day && x.time===e.time)).length; $('pick-help').textContent=conflicts ? `${conflicts} simultaneous set${conflicts===1?'':'s'} in your picks` : 'No conflicts detected'; $('picks').innerHTML=picked.length ? picked.map(e=>`<button class="pick" data-id="${escape(idFor(e))}" title="Remove ${escape(e.artist)}"><small>${e.day} · ${e.time}</small>${escape(e.artist)} ×</button>`).join('') : '<span class="muted">Pick artists from the timetable below.</span>'; $('picks').querySelectorAll('button').forEach(b=>b.onclick=()=>{selected.delete(b.dataset.id); save(); render();}); }
function linkLabel(url) { try { return new URL(url).hostname.replace(/^www\./,''); } catch { return 'Official link'; } }
function showDetail(e) { const active=selected.has(idFor(e)); const tags=(e.genres||'').split(';').map(x=>x.trim()).filter(Boolean); const links=[...new Set(e.links||[])]; const image=e.avatar ? `<img class="detail-avatar" src="${escape(e.avatar)}" alt="${escape(e.artist)}">` : `<div class="detail-avatar fallback" aria-hidden="true">${escape(e.artist[0]||'?')}</div>`; const followers=Number(e.followers||0); $('detail-content').innerHTML=`<div class="detail-head">${image}<div><h2>${escape(e.artist)}</h2><p class="detail-meta">${escape(e.day)} · ${escape(e.time)}${e.end?` – ${escape(e.end)}`:''} · ${escape(e.stage)}${followers?` · ${followers.toLocaleString()} SoundCloud followers`:''}</p></div></div>${tags.length?`<div class="detail-tags">${tags.map(tag=>`<span class="detail-tag">${escape(tag)}</span>`).join('')}</div>`:''}<p class="detail-body">${escape(e.description||'No artist biography is available yet.')}</p>${links.length?`<div class="detail-links">${links.map(url=>`<a class="detail-link" href="${escape(url)}" target="_blank" rel="noreferrer">${escape(linkLabel(url))} ↗</a>`).join('')}</div>`:'<p class="muted">No official links are available for this artist.</p>'}<button id="detail-star" class="detail-star">${active?'★ Remove from my schedule':'☆ Add to my schedule'}</button>`; $('detail-star').onclick=()=>{const id=idFor(e); active?selected.delete(id):selected.add(id); save(); render(); showDetail(e);}; $('detail').showModal(); }
const groupKey = value => (value||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase().split(/[\/&]/).map(part=>part.replace(/[^a-z0-9]/g,'')).filter(Boolean).sort().join('|');
const overlaps = (a,b) => minutes(a.time) < endMinutes(b) && endMinutes(a) > minutes(b.time);
function renderSchedule() {
  const dayEvents=events.filter(e=>e.day===day), stages=[...new Set(dayEvents.map(e=>e.stage))], heatThreshold=3000;
  const kittin=Number(events.find(e=>e.artist==='Kittin')?.followers)||0, maxFollowers=Math.max(heatThreshold,kittin,...events.map(e=>Number(e.followers)||0)), heatSpan=Math.max(1,Math.log10(maxFollowers/heatThreshold));
  const collectiveMembers=new Map(), memberIds=new Set();
  dayEvents.filter(e=>e.is_collective).forEach(group=>{
    const members=dayEvents.filter(e=>!e.is_collective && groupKey(e.collective)===groupKey(group.artist) && e.stage===group.stage && overlaps(e,group));
    if(members.length) { collectiveMembers.set(idFor(group),members); members.forEach(member=>memberIds.add(idFor(member))); }
  });
  const schedule=$('timetable'); schedule.innerHTML=''; const grid=document.createElement('div'); grid.className='schedule'; grid.style.setProperty('--stages',stages.length);
  grid.innerHTML='<div class="time-head"></div>'+stages.map((s,i)=>`<div class="stage" style="grid-column:${i+2}">${escape(s)}</div><div class="stage-bg" style="grid-column:${i+2}"></div>`).join('');
  for(let hour=0;hour<24;hour++){ const row=hour*6+2; grid.insertAdjacentHTML('beforeend',`<div class="hour" style="grid-row:${row}/span 6">${String(hour).padStart(2,'0')}:00</div><div class="line" style="grid-row:${row}"></div>`); }
  collectiveMembers.forEach((members,groupId)=>{
    const group=dayEvents.find(e=>idFor(e)===groupId), start=minutes(group.time), row=Math.floor(start/10)+2, span=Math.max(4,Math.ceil((endMinutes(group)-start)/10));
    const rail=document.createElement('button'); rail.className='collective-rail'; rail.style.gridColumn=stages.indexOf(group.stage)+2; rail.style.gridRow=`${row}/span ${span}`; rail.textContent=group.artist; rail.title=`${group.artist}: ${members.map(e=>e.artist).join(', ')}`;
    rail.onclick=()=>showDetail(group); grid.append(rail);
  });
  dayEvents.forEach(e=>{
    if(collectiveMembers.has(idFor(e))) return;
    const position=minutes(e.time), row=Math.floor(position/10)+2, span=Math.max(4,Math.ceil((endMinutes(e)-position)/10)), active=selected.has(idFor(e)), hidden=picksOnly&&!active, followers=Number(e.followers)||0, emphasized=followers>=heatThreshold, heat=emphasized?Math.min(1,Math.log10(followers/heatThreshold)/heatSpan):0, grouped=memberIds.has(idFor(e));
    const el=document.createElement('div'); el.className=`event ${active?'selected':''} ${emphasized?'has-listeners':''} ${grouped?'group-member':''} ${hidden?'hidden':''}`;
    if(emphasized) { el.style.setProperty('--heat-light',`${23+heat*43}%`); el.style.setProperty('--heat-saturation',`${40+heat*38}%`); }
    el.style.gridColumn=stages.indexOf(e.stage)+2; el.style.gridRow=`${row}/span ${span}`; el.title=`${e.time}${e.end?` – ${e.end}`:''} · ${e.stage} · ${e.artist}${e.collective?` · ${e.collective}`:''}`;
    el.innerHTML=`<button class="event-star" aria-label="${active?'Remove':'Add'} ${escape(e.artist)} ${active?'from':'to'} my schedule">${active?'★':'☆'}</button><button class="event-card"><span class="name">${escape(e.artist)}</span></button>`;
    el.querySelector('.event-star').onclick=()=>{const id=idFor(e); selected.has(id)?selected.delete(id):selected.add(id); save(); render();}; el.querySelector('.event-card').onclick=()=>showDetail(e); grid.append(el);
  });
  schedule.append(grid); const first=Math.min(...dayEvents.map(e=>minutes(e.time))); requestAnimationFrame(()=>{schedule.scrollTop=Math.max(0,Math.floor(first/10)*11-20);});
}
function render(){ renderDays(); renderPicks(); renderSchedule(); $('only-picks').classList.toggle('active',picksOnly); $('only-picks').setAttribute('aria-pressed',picksOnly); }
applyPalette(localStorage.getItem(paletteKey)||'acid'); $('palette').onchange=e=>applyPalette(e.target.value); $('only-picks').onclick=()=>{picksOnly=!picksOnly; render();}; $('clear').onclick=()=>{ if(selected.size && confirm('Clear every artist from your custom schedule?')) { selected.clear(); save(); render(); } }; $('detail-close').onclick=()=>$('detail').close(); $('detail').addEventListener('click',e=>{if(e.target===$('detail')) $('detail').close();}); render();
</script></body></html>'''


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lineup", type=Path, default=Path("lineup.txt"))
    parser.add_argument("--artists", type=Path, default=Path("whole_soundcloud_artists.csv"))
    parser.add_argument("--end-times", type=Path, default=Path("schedule_end_times_from_screenshots.csv"))
    parser.add_argument("--output", type=Path, default=Path("index.html"))
    args = parser.parse_args()
    events = load_events(args.lineup, load_artist_metadata(args.artists), load_end_times(args.end_times))
    if not events:
        raise SystemExit("No timetable events found in lineup file.")
    args.output.write_text(TEMPLATE.replace("__SCHEDULE_DATA__", json.dumps(events, ensure_ascii=False)), encoding="utf-8")
    print(f"wrote {len(events)} events to {args.output}")


if __name__ == "__main__":
    main()
