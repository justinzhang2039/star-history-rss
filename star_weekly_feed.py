#!/usr/bin/env python3
"""Star History Weekly -> RSS. Items only for: repos newly entering the weekly top 20 (green N), and repos newly entering the top 5."""
import json, re, sys, os, datetime, urllib.request, html
from email.utils import format_datetime
BASE="https://www.star-history.com"; UA={"User-Agent":"Mozilla/5.0 star-weekly-feed"}
STATE=os.environ.get("STATE","state.json"); OUT=os.environ.get("OUT","star-history-weekly.xml"); TOPN=5; MAXITEMS=100
get=lambda u: urllib.request.urlopen(urllib.request.Request(u,headers=UA),timeout=60).read().decode("utf-8","ignore")
def fetch_weekly():
    home=get(BASE+"/"); js=re.search(r'src="(/assets/index-[^"]+\.js)"',home).group(1); t=get(BASE+js)
    m=re.search(r'="([A-Z][a-z]{2} \d{1,2}, \d{4})",\w+="([A-Z][a-z]{2} \d{1,2}, \d{4})",\w+=(\[\{name:"[^"]+",new_stars:.*?\}\])',t,re.S)
    if not m: sys.exit("weekly block not found (site layout changed?)")
    arr=re.sub(r'([{,])(\w+):',r'\1"\2":',m.group(3)).replace('void 0','null')
    return m.group(1),m.group(2),json.loads(arr)
def main():
    frm,to,repos=fetch_weekly(); win=f"{frm} – {to}"  # rolling 7-day window, refreshed daily
    st=json.load(open(STATE)) if os.path.exists(STATE) else {"window":None,"top20":None,"top5":None,"items":[]}
    if st.get("window")==win and "--force" not in sys.argv: print("window unchanged, no update"); write(st); return
    now=format_datetime(datetime.datetime.now(datetime.timezone.utc)); new=[]
    names=[r["name"] for r in repos]; top=names[:TOPN]
    first=st.get("top20") is None
    for i,r in enumerate(repos,1):
        entered = (r.get("rank_change") is None) if first else (r["name"] not in st["top20"])
        if entered: new.append(("new",i,r))
    if not first:
        for i,n in enumerate(top,1):
            if n not in st["top5"]: new.append(("top5",i,repos[i-1]))
    for kind,rank,r in new:
        n=r["name"]; lab="🆕 新进榜单 Top20" if kind=="new" else f"🔥 新进前{TOPN}"
        t5=" / ".join(f"{x['name'].split('/')[-1]} +{x['new_stars']:,}" for x in repos[:TOPN])
        title=f"{lab} #{rank} {n}（+{r['new_stars']:,} ★）" if kind=="new" else f"{lab} #{rank} {n}｜前{TOPN}：{t5}"
        st["items"].insert(0,{"title":title,
          "link":f"https://github.com/{n}","guid":f"{win}|{kind}|{n}","pubDate":now,
          "desc":(f"当前前{TOPN}（各自近7天新增星）：<br>"+"<br>".join(f"#{j} <a href='https://github.com/{x['name']}'>{x['name']}</a> +{x['new_stars']:,} ★"+(" ← 新进" if x['name']==n else "") for j,x in enumerate(repos[:TOPN],1))+"<br><br>" if kind=="top5" else "")+f"统计窗口：{win}（每日滚动）<br>当前排名：#{rank}<br>近7天新增星：+{r['new_stars']:,}<br>总星数：{r['stars_total']:,}<br>"
                 f"<a href='https://www.star-history.com/#{n}&amp;Date'>Star History 曲线</a> · <a href='https://github.com/{n}'>GitHub</a>"})
    st.update(window=win,top20=names,top5=top,items=st["items"][:MAXITEMS]); st.pop("week",None)
    json.dump(st,open(STATE,"w"),ensure_ascii=False,indent=1)
    print(f"{win}: {len(new)} new items"); write(st)
def write(st):
    e=html.escape; it="".join(f"<item><title>{e(i['title'])}</title><link>{e(i['link'])}</link><guid isPermaLink='false'>{e(i['guid'])}</guid><pubDate>{i['pubDate']}</pubDate><description>{e(i['desc'])}</description></item>" for i in st["items"])
    open(OUT,"w").write(f"<?xml version='1.0' encoding='UTF-8'?><rss version='2.0'><channel><title>Star History 周榜（滚动）：新上榜 &amp; 新进前{TOPN}</title><link>{BASE}</link><description>只在滚动周榜前20出现新项目或有新项目进入前{TOPN}时更新</description>{it}</channel></rss>")
main()
