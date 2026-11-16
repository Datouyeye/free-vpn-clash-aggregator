# Free VPN Clash Aggregator（配额轮询 + 国内直连分流版）

聚合 10 个公开 GitHub Clash 节点项目为一个 Clash Meta 配置，GitHub Actions 每 15 分钟重新抓取并提交生成文件。

基于 [1000ttank/free-vpn-clash-aggregator](https://github.com/1000ttank/free-vpn-clash-aggregator) 改造，两处关键差异：

| 改动 | 原版 | 本版 |
| --- | --- | --- |
| 节点配额 | 按 sources.yaml 顺序切片取前 500，实交只有头两个源贡献节点 | 轮转取（round-robin），10 个源全量参与，小源全进、大源均摊 |
| 分流 | 只有 `MATCH,PROXY`，全部流量走代理 | `GEOIP,LAN` → `GEOIP,CN` → 其余走代理，国内站点直连 |
| 测速间隔 | 300 秒 | 600 秒（节点来自 10 个源，降低测速开销） |

## Clash Verge Rev 导入

在「订阅」中新建，粘贴（把 `OWNER` 换成你的 GitHub 用户名）：

```text
https://raw.githubusercontent.com/OWNER/free-vpn-clash-aggregator/main/output/clash.yaml
```

`output/source-status.json` 可查看每个上游最近一次抓取结果和各源入选节点数。

### 中国大陆网络：raw 域名被阻断时的替代地址

`raw.githubusercontent.com` 在国内常因 SNI 阻断而 TLS 握手失败（客户端报 `os error 10054` / `tls handshake eof`），这不是配置错误。实测可用的替代地址（2026-11 验证，均返回完整 500 节点）：

```text
# 优先级从上到下；把 OWNER 换成你的用户名
https://gh-proxy.com/https://raw.githubusercontent.com/OWNER/free-vpn-clash-aggregator/main/output/clash.yaml
https://ghproxy.net/https://raw.githubusercontent.com/OWNER/free-vpn-clash-aggregator/main/output/clash.yaml
https://gcore.jsdelivr.net/gh/OWNER/free-vpn-clash-aggregator@main/output/clash.yaml
```

注意 `cdn.jsdelivr.net` 在国内同样不通，要用 `gcore` / `fastly` 子域。jsDelivr 走 CDN 缓存，最新性会滞后数小时，适合导入成功即可、不追求实时节点；`gh-proxy.com` 是实时透传，能跟上 15 分钟一次的更新。

前两个是第三方公共代理，只透传公开内容，不涉及你的凭据；但它们本身也可能随时失效，失效时换下一个即可。

## 第一次使用前必须做

1. 打开仓库的 **Actions** 标签页，点击 *I understand my workflows, go ahead and enable them*（新建仓库的 workflow 默认是关闭的）
2. 左侧选 *Update Clash subscription* → *Run workflow* 手动跑一次
3. 等它跑完（约 1 分钟），`output/clash.yaml` 才会存在，此时订阅链接才可用

## 本地运行

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
.venv/Scripts/python scripts/update.py
```

环境变量：

| 变量 | 默认 | 作用 |
| --- | --- | --- |
| `MAX_NODES` | 500 | 输出节点上限。不建议关掉，配置过大影响 Clash Verge 启动和测速 |
| `FETCH_TIMEOUT` | 20 | 单个上游抓取超时（秒） |
| `TEST_INTERVAL` | 600 | `AUTO` 组 url-test 间隔（秒） |

注意：本地运行需要能访问 `raw.githubusercontent.com`。国内直连会因 SSL 被阻断而全部抓取失败（脚本会报 `all upstream sources failed`），此时请挂代理或直接依赖 GitHub Actions 生成。

## 分流说明

生成的 `rules` 只有三条：

```yaml
rules:
  - GEOIP,LAN,DIRECT
  - GEOIP,CN,DIRECT
  - MATCH,PROXY
```

依赖 Clash Verge Rev 自带的 `geoip.dat`（安装后会自动下载）。这是刻意选的最轻方案：不引入远程 `rule-providers`，避免客户端运行时去拉 `raw.githubusercontent.com` 的规则集而失败。

已知局限：仅按 IP 判断，个别国内站点若域名解析到境外 CDN，会被判走代理；未处理 DNS 污染。若要更准，可后续改成 `GEOSITE,cn,DIRECT` 或接 `MetaCubeX/meta-rules-dat` 的 `.mrs` 规则集。

## 安全与合规

节点来自未知第三方公开服务，**不能视为可信 VPN**。不要通过它们登录银行、邮箱、代码仓库或传输敏感数据；请遵守所在地区法律和各上游项目许可证。上游可能随时删除节点或改变格式，工作流会在全部源失败时退出并保留上一版可用文件。

## 上游项目

见 [`sources.yaml`](sources.yaml)：PuddinCat/BestClash、Au1rxx/free-vpn-subscriptions、awesome-vpn/awesome-vpn、vxiaov/free_proxies、ermaozi/get_subscribe、anaer/Sub、ermaozi01/free_clash_vpn、peasoft/NoMoreWalls、NiceVPN123/NiceVPN、chengaopan/AutoMergePublicNodes。
