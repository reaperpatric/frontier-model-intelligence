"""
读取 aa_frontier.json，生成单文件可视化看板 aa_frontier_dashboard.html。
无外部依赖（不引入任何 CDN），数据全部内联，双击即可打开。
"""

import json
import os
from datetime import date, timedelta

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
TPL = "aa_dashboard_template.html"


def pct_change(a, b):
    return None if not a else (b - a) / a * 100


def build():
    d = json.load(open(os.path.join(OUT_DIR, "aa_frontier.json"), encoding="utf-8"))
    fr = d["frontier"]
    today = date.fromisoformat(d["generatedAt"])

    cur = fr[-1]

    def frontier_at(days_ago):
        cut = (today - timedelta(days=days_ago)).isoformat()
        val = None
        for s in fr:
            if s["date"] <= cut:
                val = s["intelligenceIndex"]
        return val

    f_12m = frontier_at(365)
    f_24m = frontier_at(730)
    first = fr[0]
    years = (today - date.fromisoformat(first["date"])).days / 365.25

    # 各厂商当前最高
    creators = []
    for name, steps in d["frontierByCreator"].items():
        creators.append({
            "name": name,
            "latest": steps[-1]["intelligenceIndex"],
            "model": steps[-1]["model"],
            "date": steps[-1]["date"],
            "steps": len(steps),
        })
    creators.sort(key=lambda c: c["latest"], reverse=True)

    # 前沿格局：领跑厂商切换次数
    leaders = []
    for s in fr:
        if not leaders or leaders[-1]["creator"] != s["creator"]:
            leaders.append({"creator": s["creator"], "from": s["date"], "model": s["model"]})

    kpi = {
        "modelCount": d["modelCount"],
        "dateRange": d["dateRange"],
        "current": round(cur["intelligenceIndex"], 2),
        "currentModel": cur["model"],
        "currentCreator": cur["creator"],
        "currentDate": cur["date"],
        "steps": len(fr),
        "first": {"date": first["date"], "value": round(first["intelligenceIndex"], 2),
                  "model": first["model"]},
        "chg12m": round(pct_change(f_12m, cur["intelligenceIndex"]), 1) if f_12m else None,
        "val12m": round(f_12m, 2) if f_12m else None,
        "val24m": round(f_24m, 2) if f_24m else None,
        "cagr": round(((cur["intelligenceIndex"] / first["intelligenceIndex"]) **
                       (1 / years) - 1) * 100, 1) if years > 0 else None,
        "years": round(years, 1),
        "leaderChanges": len(leaders) - 1,
        "leaders": leaders,
        "topCreators": creators[:12],
    }

    # 迭代节奏分析（由 analyze_cadence.py 生成）
    cad_path = os.path.join(OUT_DIR, "aa_cadence.json")
    if not os.path.exists(cad_path):
        raise SystemExit("缺少 aa_cadence.json，请先运行: python analyze_cadence.py")
    cad = json.load(open(cad_path, encoding="utf-8"))

    tpl = open(os.path.join(OUT_DIR, TPL), encoding="utf-8").read()
    html = (tpl
            .replace("/*__DATA__*/", json.dumps(d, ensure_ascii=False))
            .replace("/*__KPI__*/", json.dumps(kpi, ensure_ascii=False))
            .replace("/*__CAD__*/", json.dumps(cad, ensure_ascii=False)))
    out = os.path.join(OUT_DIR, "aa_frontier_dashboard.html")
    open(out, "w", encoding="utf-8").write(html)
    # 同步一份 index.html：GitHub Pages 只能从仓库根或 /docs 提供
    idx = os.path.join(OUT_DIR, "index.html")
    open(idx, "w", encoding="utf-8").write(html)
    print("written", out, os.path.getsize(out), "bytes")
    print("written", idx, "(Pages 入口)")
    print("KPI:", json.dumps({k: v for k, v in kpi.items()
                              if k not in ("leaders", "topCreators")}, ensure_ascii=False))


if __name__ == "__main__":
    build()
