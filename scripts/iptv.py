#!/usr/bin/env python3
"""
IPTV 直播源自动抓取、验证、合并工具
功能：
  1. 从多个公开源抓取 m3u/txt 格式的直播源
  2. 去重（按频道名+地址）
  3. 可选：验证可用性（超时检测）
  4. 输出合并后的 m3u 和 txt 文件
"""

import re
import sys
import time
import hashlib
import argparse
import concurrent.futures
from pathlib import Path
from datetime import datetime, timezone, timedelta
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

# ======================== 配置 ========================

# 默认源列表（可被 sources.txt 覆盖）
DEFAULT_SOURCES = [
    # IPTV-M3U 聚合
    "https://raw.githubusercontent.com/iptv-org/iptv/master/streams/cn.m3u",
    # vbskycn
    "https://raw.githubusercontent.com/vbskycn/iptv/master/tv/iptv4.m3u",
    # 其他社区源
    "https://raw.githubusercontent.com/YueChan-Live/IPTV/main/IPTV.m3u",
    "https://raw.githubusercontent.com/fanmingming/live/main/tv/m3u/ipv6.m3u",
    "https://live.zbds.top/tv/iptv4.m3u",
]

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
TIMEOUT = 8  # 抓取超时（秒）
VERIFY_TIMEOUT = 5  # 验证超时（秒）
MAX_WORKERS = 20  # 并发验证线程数

# 频道名标准化映射
CHANNEL_ALIASES = {
    "CCTV1": "CCTV-1 综合",
    "CCTV2": "CCTV-2 财经",
    "CCTV3": "CCTV-3 综艺",
    "CCTV4": "CCTV-4 中文国际",
    "CCTV5": "CCTV-5 体育",
    "CCTV5+": "CCTV-5+ 体育赛事",
    "CCTV6": "CCTV-6 电影",
    "CCTV7": "CCTV-7 国防军事",
    "CCTV8": "CCTV-8 电视剧",
    "CCTV9": "CCTV-9 纪录",
    "CCTV10": "CCTV-10 科教",
    "CCTV11": "CCTV-11 戏曲",
    "CCTV12": "CCTV-12 社会与法",
    "CCTV13": "CCTV-13 新闻",
    "CCTV14": "CCTV-14 少儿",
    "CCTV15": "CCTV-15 音乐",
    "CCTV16": "CCTV-16 奥林匹克",
    "CCTV17": "CCTV-17 农业农村",
    "CCTV18": "CCTV-18 购物",
    "CHC高清": "CHC高清电影",
    "CHC家庭": "CHC家庭电影",
    "CHC动作": "CHC动作电影",
}

# ======================== 工具函数 ========================

def log(msg):
    """带时间戳的日志输出"""
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def fetch_url(url):
    """下载URL内容"""
    try:
        req = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=TIMEOUT) as resp:
            data = resp.read()
            # 尝试多种编码
            for enc in ("utf-8", "gbk", "gb2312", "latin-1"):
                try:
                    return data.decode(enc)
                except (UnicodeDecodeError, LookupError):
                    continue
            return data.decode("utf-8", errors="replace")
    except (URLError, HTTPError, Exception) as e:
        log(f"  ⚠ 抓取失败 {url}: {e}")
        return None


def normalize_channel_name(name):
    """标准化频道名"""
    # 去除多余空格和特殊字符
    name = re.sub(r"\s+", " ", name).strip()
    # 去除前缀 like [NEW], ★ 等
    name = re.sub(r"^[\[【★☆●○◆◇]+.*?[\]】★☆●○◆◇]*\s*", "", name)
    # 尝试匹配别名
    upper = name.upper().replace(" ", "")
    for alias, full in CHANNEL_ALIASES.items():
        if alias.upper().replace(" ", "") in upper or upper in alias.upper().replace(" ", ""):
            return full
    return name


def make_key(channel_name, url):
    """生成去重key"""
    # 用频道名+URL的hash做去重
    return hashlib.md5(f"{channel_name}|{url}".encode()).hexdigest()


# ======================== 解析器 ========================

def parse_m3u(content):
    """解析 m3u 格式，返回 [(频道名, url, 备注), ...]"""
    channels = []
    lines = content.strip().splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("#EXTINF:"):
            # 提取频道名（最后一个逗号后面的内容）
            match = re.search(r',(.+)$', line)
            if match:
                raw_name = match.group(1).strip()
                channel_name = normalize_channel_name(raw_name)
                # 下一行是URL
                i += 1
                if i < len(lines):
                    url = lines[i].strip()
                    if url and not url.startswith("#") and url.startswith("http"):
                        channels.append((channel_name, url, raw_name))
        i += 1
    return channels


def parse_txt(content):
    """解析 txt 格式（频道名,地址 或 频道名,组别,地址），返回 [(频道名, url, 备注), ...]"""
    channels = []
    for line in content.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(",")
        if len(parts) >= 2:
            url = parts[-1].strip()
            if url.startswith("http"):
                # 倒数第二个是组别或频道名
                if len(parts) >= 3:
                    channel_name = parts[-2].strip()
                else:
                    channel_name = parts[0].strip()
                channel_name = normalize_channel_name(channel_name)
                channels.append((channel_name, url, line))
    return channels


def parse_content(content, source_url=""):
    """自动判断格式并解析"""
    content = content.strip()
    if content.startswith("#EXTM3U") or content.startswith("#EXTINF:"):
        return parse_m3u(content)
    else:
        return parse_txt(content)


# ======================== 验证 ========================

def verify_channel(channel):
    """验证单个频道是否可用，返回 (可用, channel_info)"""
    name, url, raw = channel
    try:
        req = Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=VERIFY_TIMEOUT) as resp:
            code = resp.getcode()
            if code == 200:
                return True, channel
    except Exception:
        pass
    # HEAD可能不被支持，尝试GET读取少量数据
    try:
        req = Request(url, headers={"User-Agent": USER_AGENT})
        with urlopen(req, timeout=VERIFY_TIMEOUT) as resp:
            data = resp.read(1024)
            if len(data) > 0:
                return True, channel
    except Exception:
        pass
    return False, channel


# ======================== 输出 ========================

def write_m3u(channels, filepath):
    """输出 m3u 文件"""
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        for name, url, raw in channels:
            # 按地区分组
            group = get_group(name)
            f.write(f'#EXTINF:-1 tvg-name="{name}" tvg-logo="" group-title="{group}",{name}\n')
            f.write(f"{url}\n")


def write_txt(channels, filepath):
    """输出 txt 文件"""
    with open(filepath, "w", encoding="utf-8") as f:
        for name, url, raw in channels:
            group = get_group(name)
            f.write(f"{group},{name},{url}\n")


def get_group(name):
    """根据频道名判断分组"""
    name_upper = name.upper()
    if "CCTV" in name_upper:
        return "央视"
    if any(k in name_upper for k in ["卫视", "卫视HD", "SAT"]):
        return "卫视"
    if any(k in name_upper for k in ["港澳", "香港", "澳门", "HK", "MO"]):
        return "港澳"
    if any(k in name_upper for k in ["台湾", "TW"]):
        return "台湾"
    if any(k in name_upper for k in ["地方", "都市", "新闻", "教育"]):
        return "地方"
    if any(k in name_upper for k in ["CHC", "电影", "DOUYU", "HBO"]):
        return "电影"
    if any(k in name_upper for k in ["体育", "SPORT", "足球", "篮球"]):
        return "体育"
    if any(k in name_upper for k in ["4K", "ULTRA", "UHD"]):
        return "4K"
    return "其他"


# ======================== 主流程 ========================

def load_sources(sources_file=None):
    """加载源列表"""
    if sources_file and Path(sources_file).exists():
        with open(sources_file, "r", encoding="utf-8") as f:
            urls = [line.strip() for line in f if line.strip() and not line.startswith("#")]
        log(f"从 {sources_file} 加载了 {len(urls)} 个源")
        return urls
    return DEFAULT_SOURCES


def main():
    parser = argparse.ArgumentParser(description="IPTV 直播源自动抓取合并工具")
    parser.add_argument("-s", "--sources", help="源列表文件路径")
    parser.add_argument("-o", "--output", default="tv", help="输出目录 (默认: tv)")
    parser.add_argument("--verify", action="store_true", help="启用可用性验证")
    parser.add_argument("--no-verify", action="store_true", help="禁用验证（默认）")
    parser.add_argument("--timeout", type=int, default=VERIFY_TIMEOUT, help="验证超时秒数")
    args = parser.parse_args()

    log("🎬 IPTV 直播源自动抓取合并工具")
    log("=" * 50)

    # 加载源
    source_urls = load_sources(args.sources)
    log(f"共 {len(source_urls)} 个源待抓取")

    # 抓取
    all_channels = []
    success_count = 0
    for i, url in enumerate(source_urls, 1):
        log(f"[{i}/{len(source_urls)}] 抓取: {url[:80]}...")
        content = fetch_url(url)
        if content:
            channels = parse_content(content, url)
            log(f"  ✓ 获取到 {len(channels)} 个频道")
            all_channels.extend(channels)
            success_count += 1
        else:
            log(f"  ✗ 失败")

    log(f"\n抓取完成: {success_count}/{len(source_urls)} 个源成功, 共 {len(all_channels)} 个频道")

    if not all_channels:
        log("❌ 没有获取到任何频道，退出")
        sys.exit(1)

    # 去重
    seen = {}
    unique_channels = []
    for ch in all_channels:
        key = make_key(ch[0], ch[1])
        if key not in seen:
            seen[key] = True
            unique_channels.append(ch)

    log(f"去重后: {len(unique_channels)} 个频道 (去掉了 {len(all_channels) - len(unique_channels)} 个重复)")

    # 验证
    if args.verify:
        log(f"\n🔍 开始验证频道可用性 (超时 {args.timeout}s)...")
        valid_channels = []
        invalid_count = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(verify_channel, ch): ch for ch in unique_channels}
            done = 0
            for future in concurrent.futures.as_completed(futures):
                done += 1
                ok, ch = future.result()
                if ok:
                    valid_channels.append(ch)
                else:
                    invalid_count += 1
                if done % 50 == 0 or done == len(unique_channels):
                    log(f"  进度: {done}/{len(unique_channels)} (可用: {len(valid_channels)}, 不可用: {invalid_count})")
        log(f"验证完成: {len(valid_channels)}/{len(unique_channels)} 个频道可用")
        unique_channels = valid_channels
    else:
        log("跳过验证（使用 --enable 启用）")

    # 按频道名排序
    unique_channels.sort(key=lambda x: (get_group(x[0]), x[0]))

    # 输出
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone(timedelta(hours=8)))
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")

    m3u_path = output_dir / "iptv.m3u"
    txt_path = output_dir / "iptv.txt"

    write_m3u(unique_channels, m3u_path)
    write_txt(unique_channels, txt_path)

    # 写入更新信息
    info_path = output_dir / "info.txt"
    with open(info_path, "w", encoding="utf-8") as f:
        f.write(f"最近更新时间: {timestamp}\n")
        f.write(f"频道总数: {len(unique_channels)}\n")
        f.write(f"数据源数: {len(source_urls)}\n")
        f.write(f"成功抓取: {success_count}\n")
        groups = {}
        for ch in unique_channels:
            g = get_group(ch[0])
            groups[g] = groups.get(g, 0) + 1
        for g, c in sorted(groups.items()):
            f.write(f"  {g}: {c} 个频道\n")

    log(f"\n✅ 输出完成:")
    log(f"  M3U: {m3u_path} ({len(unique_channels)} 个频道)")
    log(f"  TXT: {txt_path}")
    log(f"  信息: {info_path}")
    log(f"  更新时间: {timestamp}")

    # 统计
    groups = {}
    for ch in unique_channels:
        g = get_group(ch[0])
        groups[g] = groups.get(g, 0) + 1
    log(f"\n📊 频道分布:")
    for g, c in sorted(groups.items(), key=lambda x: -x[1]):
        log(f"  {g}: {c}")


if __name__ == "__main__":
    main()
