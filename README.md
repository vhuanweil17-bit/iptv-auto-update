# 📺 IPTV Auto Update

自动抓取、验证、合并 IPTV 直播源。每天自动更新，支持 IPv4/IPv6。

## 功能

- 🔄 **每天自动更新** — GitHub Actions 定时抓取
- 🌐 **多源聚合** — 从多个公开 IPTV 源合并
- 🔍 **自动去重** — 按频道名+地址去重
- ✅ **可用性验证** — 自动检测频道是否能播放
- 📁 **双格式输出** — 同时生成 m3u 和 txt 格式
- 🏷️ **智能分组** — 央视/卫视/港澳/地方等自动分类

## 直播源地址

更新后的直播源会自动提交到本仓库：

| 格式 | 地址 |
|------|------|
| M3U | `https://raw.githubusercontent.com/你的用户名/iptv-auto-update/main/tv/iptv.m3u` |
| TXT | `https://raw.githubusercontent.com/你的用户名/iptv-auto-update/main/tv/iptv.txt` |

## 使用方法

### 1. 直接使用
将上面的 M3U 地址填入你的 IPTV 播放器（IPTV Pro、VLC、PotPlayer 等）。

### 2. 添加自定义源
编辑 `sources.txt`，每行添加一个 IPTV 源的 URL：

```
https://example.com/your-source.m3u
https://another-source.txt
```

### 3. 本地运行
```bash
python scripts/iptv.py -s sources.txt -o tv --verify
```

### 4. 手动触发更新
进入 GitHub 仓库 → Actions → Update IPTV Sources → Run workflow

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `--verify` | 启用频道可用性验证 | 关闭 |
| `--timeout N` | 验证超时秒数 | 5 |
| `-s FILE` | 源列表文件 | sources.txt |
| `-o DIR` | 输出目录 | tv |

## 免责声明

本项目仅用于技术研究和学习交流。所有直播源均来自互联网公开资源，本项目不对其内容负责，不保证源的可用性和合法性。使用本项目即表示你已阅读并同意此声明。
