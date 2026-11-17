# Free VPN Clash Aggregator（配额轮询 + 国内直连分流版）

聚合 10 个公开 GitHub Clash 节点项目为一个 Clash Meta 配置，GitHub Actions 每 15 分钟重新抓取并提交生成文件。

基于 [1000ttank/free-vpn-clash-aggregator](https://github.com/1000ttank/free-vpn-clash-aggregator) 改造，两处关键差异：

| 改动 | 原版 | 本版 |
| --- | --- | --- |
| 节点配额 | 按 sources.yaml 顺序切片取前 500，实交只有头两个源贡献节点 | 轮转取（round-robin），10 个源全量参与，小源全进、大源均摊 |
| 分流 | 只有 `MATCH,PROXY`，全部流量走代理 | `GEOIP,LAN` → `GEOIP,CN` → 其余走代理，国内站点直连 |
| 代理分组 | 单个 `AUTO` 混合测速全部 500 个节点 | 拆成 `AUTO`（非 QUIC）+ `AUTO-HY2`（hysteria2 单独测速），避免低延迟 vmess 长期压制 QUIC 节点 |

## Clash Verge Rev 导入

在「订阅」中新建，粘贴（把 `OWNER` 换成你的 GitHub 用户名）：

```text
https://raw.githubusercontent.com/OWNER/free-vpn-clash-aggregator/main/output/clash.yaml
```

`output/source-status.json` 里 `kept_per_source` 是**每个源去重后的可用节点数**，不等于最终被选入配置的节点数（受 `MAX_NODES` 上限和轮转分配影响）。

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

1. 打开仓库的 **Actions** 标签页。**fork 来的仓库**在这里点 *I understand my workflows, go ahead and enable them*；自己新建仓库再 push 的（workflow 已是 `active`）可跳过这步
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
| `TEST_INTERVAL` | 300 | `AUTO` / `AUTO-HY2` 组的 url-test 间隔（秒） |

注意：本地运行需要能访问 `raw.githubusercontent.com`。国内直连会因 SSL 被阻断而全部抓取失败（脚本会报 `all upstream sources failed`），此时请挂代理或直接依赖 GitHub Actions 生成。

## 代理分组

| 组 | 类型 | 成员 | 作用 |
| --- | --- | --- | --- |
| `AUTO` | url-test | 非 QUIC 节点 | 每 300 秒测速，选延迟最低的 |
| `AUTO-HY2` | url-test | 仅 hysteria2 | 同上，把 QUIC 节点单独拉出来比 |
| `PROXY` | select | 上两组 + DIRECT + 全部节点 | 分流规则最终指向它 |

`PROXY` 默认选 `AUTO`。**一旦手动点了某个具体节点，客户端会记住这个选择（`store-selected`），`AUTO` 的自动选优就不再生效** —— 遇到“怎么不自动挑节点了”，先看这里是不是被手点过。

为什么拆 `AUTO-HY2`：hysteria2 走 QUIC，带宽和抗丢包通常明显好于 vmess/ss，但基于单次 HTTP 探测的延迟数字往往更高。混在一个 url-test 里，它会被低延迟的 vmess 长期压制，几乎永远选不到。

`url-test` 是**定时选优，不是故障转移**：当前节点中途挂掉不会立刻切换，最多要等一个测速周期（300 秒），期间那几次请求会先失败。`tolerance: 50` 表示新节点要比当前快 50ms 以上才切，避免在相近节点间来回抖动。

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
