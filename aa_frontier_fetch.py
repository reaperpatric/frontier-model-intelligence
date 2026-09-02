"""
Artificial Analysis 数据抓取脚本
=================================
抓取 artificialanalysis.ai 的 Frontier Language Model Intelligence 数据。

原理：
1. 请求首页 HTML，页面为 Next.js RSC 流式渲染，数据清单（manifest）内嵌在
   self.__next_f.push(...) 的 payload 中，形如：
   {"path":"/data/xxxx.txt","key":"<64位hex>"}
2. 真正的全量数据不在 HTML 里，而是加密放在 /data/*.txt：
   - key     = hex 解码 manifest.key（32 字节）
   - iv      = SHA256(key)[:12]
   - 算法     = AES-256-GCM（tagLength 128）
   - 明文     = gzip 压缩的 JSON
3. 解密 + 解压后得到全量数据，其中 models[] 含 releaseDate + intelligenceIndex，
   据此可还原 "Frontier Language Model Intelligence, Over Time" 阶梯曲线。

依赖：pip install cryptography
输出：aa_models.csv / aa_frontier.csv / aa_frontier_by_creator.csv / aa_raw_models.json
"""

import csv
import gzip
import hashlib
import json
import os
import re
import urllib.request
from datetime import date

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

BASE = "https://artificialanalysis.ai"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
OUT_DIR = os.path.dirname(os.path.abspath(__file__))

# 主要指标列（导出 CSV 用）
METRIC_COLS = [
    "intelligenceIndex", "agenticIndex", "omniscience", "gdpval",
    "gpqa", "hle", "aime25", "livecodebench", "terminalbenchV21",
    "scicode", "lcr", "mmmuPro", "critpt", "tau2", "tauBanking",
    "ifbench", "mlcrOverall", "apexAgents", "itBenchSre", "analystAgent",
    "enterpriseOpsGym",
]
PRICE_COLS = [
    "price1mInputTokens", "price1mOutputTokens", "price1mBlended0To3To1",
    "endToEndResponseTime", "timeToFirstAnswerToken",
]


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=90).read()


def fetch_rsc_payload() -> str:
    """抓取首页并还原 RSC payload 纯文本。"""
    html = _get(BASE + "/").decode("utf-8", errors="replace")
    parts = re.findall(r"self\.__next_f\.push\(\[1,(.*?)\]\)</script>", html, re.S)
    buf = []
    for p in parts:
        try:
            buf.append(json.loads(p))
        except Exception:
            continue
    return "".join(buf)


def find_manifests(rsc: str):
    """从 RSC payload 中提取所有数据清单 (path, key)。"""
    out, seen = [], set()
    for m in re.finditer(r'\{"path":"(/data/[a-z0-9]+\.txt)","key":"([a-f0-9]+)"\}', rsc):
        if m.group(1) not in seen:
            seen.add(m.group(1))
            out.append((m.group(1), m.group(2)))
    return out


def decode_manifest(path: str, key_hex: str) -> bytes:
    """下载并解密 /data/*.txt，返回解压后的 JSON 字节。"""
    raw = _get(BASE + path)
    key = bytes.fromhex(key_hex)
    iv = hashlib.sha256(key).digest()[:12]
    plain = AESGCM(key).decrypt(iv, raw, None)
    return gzip.decompress(plain)


def build_frontier(models):
    """Frontier 曲线：截至每个时点的历史最高智能指数（阶梯图）。"""
    pts = [m for m in models if m.get("releaseDate") and m.get("intelligenceIndex") is not None]
    pts.sort(key=lambda m: (m["releaseDate"], -m["intelligenceIndex"]))
    best, steps = -1.0, []
    for m in pts:
        v = m["intelligenceIndex"]
        if v > best:
            best = v
            prev = steps[-1]["intelligenceIndex"] if steps else None
            steps.append({
                "date": m["releaseDate"],
                "intelligenceIndex": round(v, 4),
                "deltaVsPrevStep": round(v - prev, 4) if prev is not None else None,
                "model": m["name"],
                "slug": m.get("slug"),
                "creator": (m.get("creator") or {}).get("name"),
                "isOpenWeights": m.get("isOpenWeights"),
                "isReasoning": m.get("isReasoning"),
            })
    return steps


def build_frontier_by_creator(models, min_models: int = 2):
    """各厂商自身的智能指数演进（各取历史最高台阶）。"""
    by = {}
    for m in models:
        if not m.get("releaseDate") or m.get("intelligenceIndex") is None:
            continue
        c = (m.get("creator") or {}).get("name") or "Unknown"
        by.setdefault(c, []).append(m)
    out = {}
    for c, ms in by.items():
        steps = build_frontier(ms)
        if len(steps) >= min_models:
            out[c] = steps
    return dict(sorted(out.items(), key=lambda kv: kv[1][-1]["intelligenceIndex"], reverse=True))


def write_csv(path, rows, cols):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def main():
    today = date.today().isoformat()
    print("[1/5] 抓取首页 RSC payload ...")
    rsc = fetch_rsc_payload()
    print(f"      payload {len(rsc):,} 字符")

    print("[2/5] 提取数据清单 ...")
    mans = find_manifests(rsc)
    for p, k in mans:
        print(f"      {p}  key={k[:12]}...")

    print("[3/5] 解密下载全量数据 ...")
    decoded = {}
    for p, k in mans:
        js = decode_manifest(p, k)
        name = os.path.basename(p).replace(".txt", "")
        decoded[name] = json.loads(js)
        open(os.path.join(OUT_DIR, f"aa_raw_{name}.json"), "wb").write(js)
        print(f"      {p} -> {type(decoded[name]).__name__} ({len(js):,} bytes)")

    # 主数据集：含 models 列表的那个
    data = None
    for v in decoded.values():
        if isinstance(v, dict) and isinstance(v.get("models"), list):
            data = v
            break
    if data is None:
        raise SystemExit("未找到包含 models 的数据集")

    models = data["models"]
    models = [m for m in models if m.get("releaseDate") and m.get("intelligenceIndex") is not None]
    models.sort(key=lambda m: m["releaseDate"])
    print(f"[4/5] 有效模型 {len(models)} 个，"
          f"{models[0]['releaseDate']} ~ {models[-1]['releaseDate']}")

    # 全量模型 CSV
    rows = []
    for m in models:
        r = {
            "releaseDate": m["releaseDate"],
            "name": m["name"],
            "shortName": m.get("shortName"),
            "slug": m.get("slug"),
            "creator": (m.get("creator") or {}).get("name"),
            "isOpenWeights": m.get("isOpenWeights"),
            "isReasoning": m.get("isReasoning"),
            "sizeClass": m.get("sizeClass"),
            "intelligenceIndexIsEstimated": m.get("intelligenceIndexIsEstimated"),
            "deprecated": m.get("deprecated"),
        }
        for c in METRIC_COLS + PRICE_COLS:
            r[c] = m.get(c)
        rows.append(r)
    write_csv(os.path.join(OUT_DIR, "aa_models.csv"), rows,
              ["releaseDate", "name", "shortName", "slug", "creator",
               "isOpenWeights", "isReasoning", "sizeClass",
               "intelligenceIndexIsEstimated", "deprecated"] + METRIC_COLS + PRICE_COLS)

    # Frontier 阶梯
    steps = build_frontier(models)
    write_csv(os.path.join(OUT_DIR, "aa_frontier.csv"), steps,
              ["date", "intelligenceIndex", "deltaVsPrevStep", "model", "slug",
               "creator", "isOpenWeights", "isReasoning"])

    # 分厂商 frontier
    by_creator = build_frontier_by_creator(models)
    rows = []
    for c, ss in by_creator.items():
        for s in ss:
            rows.append({"creator": c, **s})
    write_csv(os.path.join(OUT_DIR, "aa_frontier_by_creator.csv"), rows,
              ["creator", "date", "intelligenceIndex", "deltaVsPrevStep",
               "model", "slug", "isOpenWeights", "isReasoning"])

    # 给前端用的 JSON
    payload = {
        "generatedAt": today,
        "source": "artificialanalysis.ai",
        "modelCount": len(models),
        "dateRange": [models[0]["releaseDate"], models[-1]["releaseDate"]],
        "frontier": steps,
        "frontierByCreator": by_creator,
        "models": [{
            "date": m["releaseDate"],
            "name": m["name"],
            "creator": (m.get("creator") or {}).get("name"),
            "intel": round(m["intelligenceIndex"], 3),
            "open": m.get("isOpenWeights"),
            "est": m.get("intelligenceIndexIsEstimated"),
            "price": m.get("price1mBlended0To3To1"),
        } for m in models],
    }
    with open(os.path.join(OUT_DIR, "aa_frontier.json"), "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)

    print(f"[5/5] 完成。Frontier 台阶 {len(steps)} 级，厂商 {len(by_creator)} 家")
    print(f"      {steps[0]['date']} {steps[0]['model']} {steps[0]['intelligenceIndex']}"
          f"  ->  {steps[-1]['date']} {steps[-1]['model']} {steps[-1]['intelligenceIndex']}")


if __name__ == "__main__":
    main()
