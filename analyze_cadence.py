"""
前沿模型迭代节奏分析
====================
回答：占据智能指数 Top-3 席位的前沿模型，其"新版本"多久迭代一次？

口径说明（三种）：
  A. 厂商版本迭代间隔【主口径】—— 同一厂商连续两次发布「进入 Top-3 的新版本」的日期差。
     例：Anthropic 的 Claude Opus 4.7 → Claude Opus 5，中间隔了多少天。
  B. Top-3 席位更替间隔 —— Top-3 阵容发生变化的相邻日期差（含跨厂商挤位）。
  C. 榜首易主间隔 —— 第 1 名换人的相邻日期差。

数据清洗要点：
  AA 把同一模型的不同 reasoning effort（xhigh / high / medium / low）记为独立模型且同日发布，
  直接计算会产生大量 0 天间隔。因此先按 (厂商, 去括号系列名, 发布日期) 合并，取最高分那条。

月度模块（START_MONTH 起，默认 2026-01）：
  月度样本很稀疏（每月 0~3 次迭代），因此同时给出：
    - 当月原始迭代次数、当月间隔中位数
    - 滚动 3 个月中位间隔（平滑后的趋势，主看这根线）
    - 前沿指数月增量（每月都有值，衡量「智能提升速度」，与迭代频率互补）

输入：aa_models.csv（由 aa_frontier_fetch.py 生成）
输出：aa_cadence.json
"""

import calendar
import csv
import json
import os
import statistics as st
from collections import defaultdict
from datetime import date

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
TOP_N = 3
START_MONTH = "2026-01"   # 月度分析的起始月份


def base_name(name: str) -> str:
    """去掉 reasoning effort 等括号后缀：'Claude Fable 5.1 (Adaptive Reasoning, Max Effort)' -> 'Claude Fable 5.1'"""
    return name.split("(")[0].strip()


def load_versions():
    rows = list(csv.DictReader(open(os.path.join(OUT_DIR, "aa_models.csv"), encoding="utf-8-sig")))
    best = {}
    for r in rows:
        d, name, creator = r["releaseDate"], r["name"], r["creator"]
        if not d or not r["intelligenceIndex"] or not creator:
            continue
        try:
            intel = float(r["intelligenceIndex"])
        except ValueError:
            continue
        key = (creator, base_name(name), d)
        rec = {
            "date": d,
            "name": name,
            "base": base_name(name),
            "creator": creator,
            "intel": round(intel, 4),
            "open": r.get("isOpenWeights") == "True",
        }
        if key not in best or intel > best[key]["intel"]:
            best[key] = rec
    vs = sorted(best.values(), key=lambda m: (m["date"], -m["intel"]))
    return vs


def simulate_top3(versions):
    """按时间推进维护累计最高 Top-3。

    返回 (raw_events, merged)：
      raw_events —— 每一次进出都记录，用于计算「模型在榜时长」（配对必须精确）
      merged     —— 同一天合并为一次「更替日」，含当天最终的 Top-3 快照，用于计算间隔
    """
    top, events = [], []
    by_day = {}
    for v in versions:
        changed = False
        exited = None
        if len(top) < TOP_N:
            top.append(v)
            changed = True
        else:
            worst = min(top, key=lambda m: m["intel"])
            if v["intel"] > worst["intel"]:
                top.remove(worst)
                exited = worst
                top.append(v)
                changed = True
        if not changed:
            continue
        top.sort(key=lambda m: -m["intel"])
        events.append({"date": v["date"], "entered": v, "exited": exited})

        # 同一天合并为一个「更替日」：entered 取当天最高分，exited 全部保留，top 取当天最终阵容
        d = v["date"]
        if d not in by_day:
            by_day[d] = {"date": d, "entered": v, "exitedAll": []}
        elif v["intel"] > by_day[d]["entered"]["intel"]:
            by_day[d]["entered"] = v
        if exited:
            by_day[d]["exitedAll"].append(exited)
        by_day[d]["top"] = [{"name": m["name"], "creator": m["creator"],
                             "intel": m["intel"]} for m in top]
    return events, list(by_day.values())


def gaps_from_dates(dates):
    ds = sorted(set(dates))
    return [(date.fromisoformat(b) - date.fromisoformat(a)).days
            for a, b in zip(ds, ds[1:])]


def summarize(gaps):
    if not gaps:
        return None
    g = sorted(gaps)
    n = len(g)
    return {
        "n": n,
        "median": round(st.median(g), 1),
        "mean": round(st.fmean(g), 1),
        "p25": round(g[max(0, int(n * 0.25) - 1)], 1),
        "p75": round(g[min(n - 1, int(n * 0.75))], 1),
        "min": g[0],
        "max": g[-1],
    }


def histogram(gaps):
    buckets = [(0, 30, "≤1 个月"), (31, 60, "1–2 个月"), (61, 90, "2–3 个月"),
               (91, 120, "3–4 个月"), (121, 180, "4–6 个月"), (181, 10 ** 6, ">6 个月")]
    out = []
    for lo, hi, label in buckets:
        out.append({"label": label, "lo": lo, "hi": hi,
                    "count": sum(1 for g in gaps if lo <= g <= hi)})
    return out


# ---------------- 月度加速度 ----------------
def month_range(a, b):
    y, m = map(int, a.split("-"))
    y2, m2 = map(int, b.split("-"))
    out = []
    while (y, m) <= (y2, m2):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def prev_month(ym):
    y, m = map(int, ym.split("-"))
    m -= 1
    if m == 0:
        m, y = 12, y - 1
    return f"{y:04d}-{m:02d}"


def last_day(ym):
    y, m = map(int, ym.split("-"))
    return f"{y:04d}-{m:02d}-{calendar.monthrange(y, m)[1]:02d}"


def build_frontier(versions):
    """累计最高智能指数序列（与 fetch.py 的 frontier 口径一致）。"""
    pts = sorted(versions, key=lambda v: (v["date"], -v["intel"]))
    best, steps = -1.0, []
    for v in pts:
        if v["intel"] > best:
            best = v["intel"]
            steps.append({"date": v["date"], "intel": v["intel"],
                          "name": v["name"], "creator": v["creator"]})
    return steps


def frontier_at(steps, day):
    v = None
    for s in steps:
        if s["date"] <= day:
            v = s["intel"]
    return v


def monthly_analysis(iter_events, versions, start_month=START_MONTH):
    steps = build_frontier(versions)
    end_month = versions[-1]["date"][:7]
    months = month_range(start_month, end_month)

    ev_by_month = defaultdict(list)
    for e in iter_events:
        ev_by_month[e["to"][:7]].append(e)

    rows = []
    for i, m in enumerate(months):
        evs = ev_by_month.get(m, [])
        gaps = [e["gap"] for e in evs]
        win = []
        for mm in months[max(0, i - 2):i + 1]:
            win += [e["gap"] for e in ev_by_month.get(mm, [])]

        f_end = frontier_at(steps, last_day(m))
        f_start = frontier_at(steps, last_day(prev_month(m)))
        delta = (round(f_end - f_start, 3)
                 if (f_end is not None and f_start is not None) else None)
        refresh = [s for s in steps if s["date"][:7] == m]

        rows.append({
            "month": m,
            "n": len(evs),
            "median": round(st.median(gaps), 1) if gaps else None,
            "mean": round(st.fmean(gaps), 1) if gaps else None,
            "roll3": round(st.median(win), 1) if win else None,
            "frontierEnd": round(f_end, 2) if f_end is not None else None,
            "frontierDelta": delta,
            "refreshCount": len(refresh),
            "refreshModels": [{"name": s["name"], "creator": s["creator"],
                               "intel": round(s["intel"], 2)} for s in refresh],
            "events": [{"creator": e["creator"], "gap": e["gap"], "to": e["to"]}
                       for e in evs],
        })
    return rows


def main():
    versions = load_versions()
    print(f"去重后模型版本 {len(versions)} 个（{versions[0]['date']} ~ {versions[-1]['date']}）")

    raw_events, events = simulate_top3(versions)
    snaps = [{"date": e["date"], "top": e["top"]} for e in events]
    print(f"Top-{TOP_N} 更替事件 {len(raw_events)} 次，合并同日后 {len(events)} 个更替日")

    # ---- A. 厂商版本迭代间隔（主口径）----
    by_creator = defaultdict(list)
    for e in events:
        by_creator[e["entered"]["creator"]].append(e["entered"]["date"])

    creator_gaps, creator_rows = {}, []
    for c, ds in by_creator.items():
        g = gaps_from_dates(ds)
        creator_gaps[c] = g
        s = summarize(g)
        creator_rows.append({
            "creator": c,
            "n": s["n"] if s else 0,
            "median": s["median"] if s else None,
            "mean": s["mean"] if s else None,
            "min": s["min"] if s else None,
            "max": s["max"] if s else None,
            "lastDate": max(ds),
            "lastGap": g[-1] if g else None,
            "gaps": g,
        })
    creator_rows.sort(key=lambda r: (r["n"], r["median"] or 0), reverse=True)

    all_creator_gaps = [g for gs in creator_gaps.values() for g in gs]

    # 每次迭代的明细（厂商 / 起止日期 / 间隔），供时间线散点图使用
    iter_events = []
    for c, ds in by_creator.items():
        ds = sorted(set(ds))
        for a, b in zip(ds, ds[1:]):
            iter_events.append({
                "creator": c, "from": a, "to": b,
                "gap": (date.fromisoformat(b) - date.fromisoformat(a)).days,
            })
    iter_events.sort(key=lambda x: x["to"])

    # ---- B. Top-3 更替间隔 ----
    ev_dates = [e["date"] for e in events]
    seat_gaps = gaps_from_dates(ev_dates)

    # ---- C. 榜首易主间隔 ----
    leader_dates, cur = [], None
    for e in events:
        top1 = e["top"][0]["name"]
        if top1 != cur:
            leader_dates.append(e["date"])
            cur = top1
    leader_gaps = gaps_from_dates(leader_dates)

    # ---- 分年度趋势（按间隔结束年份）----
    year_map = defaultdict(list)
    for c, ds in by_creator.items():
        ds = sorted(set(ds))
        for a, b in zip(ds, ds[1:]):
            gap = (date.fromisoformat(b) - date.fromisoformat(a)).days
            year_map[date.fromisoformat(b).year].append(gap)
    by_year = []
    for y in sorted(year_map):
        s = summarize(year_map[y])
        by_year.append({"year": y, **s})

    # ---- 更替事件明细 ----
    changelog = []
    prev = None
    for e in events:
        gap = ((date.fromisoformat(e["date"]) - date.fromisoformat(prev)).days
               if prev else None)
        ex = e["exitedAll"]
        changelog.append({
            "date": e["date"],
            "entered": e["entered"]["name"],
            "enteredCreator": e["entered"]["creator"],
            "enteredIntel": e["entered"]["intel"],
            "exited": "、".join(m["name"] for m in ex) if ex else None,
            "exitedCreator": "、".join(m["creator"] for m in ex) if ex else None,
            "gapDays": gap,
        })
        prev = e["date"]

    # ---- Top-3 席位占用次数 ----
    seat_count = defaultdict(int)
    for e in events:
        seat_count[e["entered"]["creator"]] += 1
    final_top = snaps[-1]["top"]

    # ---- 模型在榜时长：从进入 Top-3 到被挤出 ----
    entry_of, tenures = {}, []
    for e in raw_events:
        entry_of[e["entered"]["name"]] = (e["date"], e["entered"])
        if e["exited"] and e["exited"]["name"] in entry_of:
            d0, rec = entry_of.pop(e["exited"]["name"])
            tenures.append({
                "name": e["exited"]["name"],
                "creator": e["exited"]["creator"],
                "from": d0,
                "to": e["date"],
                "days": (date.fromisoformat(e["date"]) - date.fromisoformat(d0)).days,
            })
    last_date = versions[-1]["date"]
    for name, (d0, rec) in entry_of.items():
        tenures.append({
            "name": name,
            "creator": rec["creator"],
            "from": d0,
            "to": None,
            "days": (date.fromisoformat(last_date) - date.fromisoformat(d0)).days,
            "current": True,
        })
    tenures.sort(key=lambda t: -t["days"])

    # ---- 月度加速度 ----
    monthly = monthly_analysis(iter_events, versions, START_MONTH)

    out = {
        "topN": TOP_N,
        "startMonth": START_MONTH,
        "monthly": monthly,
        "versionCount": len(versions),
        "dateRange": [versions[0]["date"], versions[-1]["date"]],
        "cadence": summarize(all_creator_gaps),
        "cadenceHistogram": histogram(all_creator_gaps),
        "seat": summarize(seat_gaps),
        "leader": summarize(leader_gaps),
        "byYear": by_year,
        "byCreator": creator_rows,
        "iterEvents": iter_events,
        "changelog": changelog,
        "finalTop": final_top,
        "tenure": summarize([t["days"] for t in tenures]),
        "tenures": tenures,
        "snaps": snaps,
        "seatCount": dict(sorted(seat_count.items(), key=lambda kv: -kv[1])),
        "raw": {
            "creatorGaps": {c: g for c, g in creator_gaps.items()},
            "seatGaps": seat_gaps,
            "leaderGaps": leader_gaps,
        },
    }

    with open(os.path.join(OUT_DIR, "aa_cadence.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)

    c = out["cadence"]
    print(f"\n[A] 厂商版本迭代间隔  中位 {c['median']} 天 / 均值 {c['mean']} 天 "
          f"(n={c['n']}, P25={c['p25']}, P75={c['p75']}, 范围 {c['min']}~{c['max']})")
    print(f"[B] Top-3 更替间隔    中位 {out['seat']['median']} 天 (n={out['seat']['n']})")
    print(f"[C] 榜首易主间隔      中位 {out['leader']['median']} 天 (n={out['leader']['n']})")
    print("\n分桶:", json.dumps(out["cadenceHistogram"], ensure_ascii=False))
    print("分年度:", json.dumps(by_year, ensure_ascii=False))
    print("\nTop 厂商:")
    for r in creator_rows[:8]:
        print(f"  {r['creator']:<18} n={r['n']:<3} 中位 {r['median']} 天  最近 {r['lastDate']} (+{r['lastGap']}d)")

    print(f"\n月度加速度（{START_MONTH} 起）：")
    print("  月份     迭代  中位   滚动3月  前沿增量  月末前沿")
    for r in monthly:
        print(f"  {r['month']}  {r['n']:>3}   "
              f"{str(r['median'] or '-'):>6}  {str(r['roll3'] or '-'):>6}   "
              f"{('+' + str(r['frontierDelta'])) if r['frontierDelta'] is not None else '-':>7}   "
              f"{r['frontierEnd']}")


if __name__ == "__main__":
    main()
