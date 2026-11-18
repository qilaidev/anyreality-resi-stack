# 客户端分流规则 | Client routing rules

本页说明**客户端配置里的路由规则**：为什么需要它、规则分几层、怎么增删区域直连平台、怎么验证某个域名确实走了直连。

服务端的入站配置不做分流（`templates/singbox/03_route.json` 的 `final` 是 `direct`，节点只负责把流量放出去）。**所有分流决策都发生在客户端配置里**，也就是订阅下发的 `profile.json` / `profile.yaml`。

---

## 为什么必须有分流规则

如果你用的是**系统代理**模式，不配规则最多是本地/区域常用站点绕一圈远端网关，慢但能用。

但用 **TUN / 虚拟网卡**模式时（sing-box 官方 App、Karing、Hiddify 的默认模式），系统所有流量都被内核劫持，**没有"全局 / 直连"开关可选 —— 流量走不走远端网关完全由规则决定**。如果缺少 TUN 虚拟网卡模式下的本地/区域流量直连分流规则，直接后果是：

- 本地 CDN 与常用站点流量跨洋折返远端网关，产生额外延迟、卡顿或触发异地风控
- 本地 DNS 请求被送到远端解析 → CDN 调度到远端机房，越用越慢
- 广告 / 追踪域名照常连通，白白消耗节点流量

所以本项目下发的客户端配置**默认自带完整四层分流规则**（内含亚太区域直连规则集作为默认示例，其他地区用户可按需自定义或移除），导入即用，不需要你手动配置。

---

## 四层规则架构

`scripts/build_profile.py` 生成的 `route.rules` 按顺序匹配，**命中即停止**：

```
Layer 0  基础动作
  ├─ sniff                        协议嗅探，拿到真实域名
  ├─ protocol=dns → hijack-dns    劫持 DNS 查询交给内置 DNS 模块
  └─ ip_is_private → direct       内网 / 局域网直连

Layer 1  广告拦截
  └─ rule_set geosite-category-ads-all → reject

Layer 2  本地/区域流量直连分流（两级）
  ├─ 显式安全网 REGIONAL_SAFETY_NET → direct   ← 人工维护，内联在配置里
  ├─ rule_set geosite-cn            → direct   ← SagerNet 社区规则集（亚太区域示例）
  └─ rule_set geoip-cn              → direct   ← SagerNet 社区规则集（亚太区域示例）

Layer 3  兜底
  ├─ udp:443 → reject             拦 QUIC，逼浏览器回落 TCP
  └─ final   → 节点出站
```

### 为什么 Layer 2 要做两级

| | 显式安全网 `REGIONAL_SAFETY_NET`（内联） | `geosite-cn` 规则集 |
|---|---|---|
| 内容 | 约 60 个高频区域域名后缀，人工精选 | 数万条，社区综合维护 |
| 可见性 | 直接写在配置里，一眼能看清 | 二进制 `.srs`，黑盒 |
| 来源 | 本仓库模板（内联零外部请求） | 服务端每周拉取并内联打包（源自 `raw.githubusercontent.com`） |
| 失效风险 | 无 | 上游拉取失败或地区差异导致覆盖不全 |

`geosite-cn` 覆盖面远大于安全网，但它**依赖远程规则集源的更新与可用性**（若直接作远程规则集在客户端首次启动时下载，一旦拉取失败就会使规则集为空，导致所有本地/区域常用站点流量跨洋折返远端网关 —— 这也是"刚导入订阅时特别卡"的最常见原因）。

内联安全网 `REGIONAL_SAFETY_NET` 不依赖任何网络请求，且排在 `geosite-cn` 之前，因此即使外部规则集暂不可用，高频本地 CDN 与区域常用服务也始终直连物理网卡。

> 注：本栈已将所有规则集在服务端预先反编译并内联为 `type: inline`，客户端冷启动零外部网络请求；如作为参考添加其他区域规则，建议保持同样原则。

---

## 安全网包含哪些域名

`domain_suffix` 是**后缀匹配** —— 写 `qq.com` 就自动覆盖 `weixin.qq.com`、`music.qq.com` 等全部子域名，不需要逐个列子域名。

| 类别 | 域名后缀 |
|---|---|
| 腾讯系 | `qq.com`, `wechat.com`, `tencent.com` |
| 阿里系 | `alipay.com`, `taobao.com`, `tmall.com`, `aliyun.com`, `aliyuncs.com`, `alicdn.com` |
| 字节系 | `douyin.com`, `toutiao.com`, `ixigua.com` |
| 百度系 | `baidu.com`, `baiducontent.com`, `bdstatic.com` |
| 京东 / 拼多多 | `jd.com`, `jdpay.com`, `pinduoduo.com` |
| 视频 | `bilibili.com`, `biligame.com`, `iqiyi.com`, `youku.com`, `ximalaya.com`, `kuaishou.com` |
| 网易 / 新浪 | `163.com`, `126.com`, `sina.com.cn`, `sinaimg.cn`, `weibo.com` |
| 本地生活 | `meituan.com`, `dianping.com`, `sankuai.com`, `ele.me`, `didiglobal.com` |
| 出行 / 住宿 | `ctrip.com`, `12306.cn`, `qunar.com`, `mafengwo.cn`, `lianjia.com` |
| 地图 | `amap.com`, `autonavi.com` |
| 办公 | `dingtalk.com`, `feishu.cn`, `larksuite.com` |
| 银行 | `icbc.com.cn`, `ccb.com`, `abchina.com`, `bankofchina.com`, `bankcomm.com` |
| 社区 / 资讯 | `zhihu.com`, `xiaohongshu.com`, `douban.com`, `csdn.net`, `36kr.com`, `huxiu.com`, `xueqiu.com`, `zhipin.com` |
| 机构域名 | `gov.cn`, `edu.cn`, `org.cn`, `com.cn` |

完整列表以 [`scripts/build_profile.py`](../../scripts/build_profile.py) 里的 `REGIONAL_SAFETY_NET` 为准；渲染后的样例见 [`examples/single-node/sing-box-client-config.json`](../../examples/single-node/sing-box-client-config.json)。

---

## 增删区域直连平台

**改模板（影响后续所有安装）：**

```bash
# 1. 高频域名加进 build_profile.py 的 REGIONAL_SAFETY_NET（内联安全网，不依赖任何下载）；
#    区域 CDN 类域名加进 data/geosite-cn-extra.json 的 domain_suffix 数组
vim scripts/build_profile.py          # 或 data/geosite-cn-extra.json

# 2. 重新生成样例并跑门禁（examples/ 有漂移检查，必须同步）
make examples
make lint test
```

**改已上线服务器（立即对现有用户生效）：**

```bash
# 注意：直接改这个文件只适合临时验证——下一次 rebuild-profiles.sh 运行时
# （每周的规则集刷新会触发）会被覆盖。长期改法见上面「改模板」。
vim /etc/anyreality-resi-stack/files/profile.json

# 校验后重启（订阅服务只是静态发文件，改完不重启也生效，但校验必须做）
sing-box check -c /etc/anyreality-resi-stack/files/profile.json

# 客户端下次自动更新订阅（默认 24h）时拉到新规则；要立刻生效就手动点刷新
```

> 客户端的订阅更新间隔由 `Profile-Update-Interval` 响应头控制，默认 24 小时，改 `UPDATE_INTERVAL_HOURS` 即可。

---

## 验证某个域名确实走了直连

**别在开着 TUN 客户端的机器上用裸 `curl` 判断出口** —— TUN 会劫持路由，`HTTP_PROXY` 环境变量还会再截一道，测出来的"通"可能是从别的代理绕出去的，结论完全不可信。

```bash
# 方法 1：绕开环境代理 + 强制物理网卡（macOS/Linux）
curl --noproxy '*' --interface en0 -sI https://www.163.com | head -3

# 方法 2：看客户端日志里这条连接实际走了哪个 outbound
#   sing-box 客户端把 log.level 调成 info 后访问该域名
journalctl -u sing-box -f | grep 163.com        # Linux
tail -f ~/Library/Logs/sing-box.log | grep 163.com   # macOS

# 方法 3：确认出口 IP 是不是你的节点
curl -x socks5h://127.0.0.1:2080 https://checkip.amazonaws.com
```

---

## 想改默认行为

| 你想要 | 怎么改 |
|---|---|
| 关掉广告拦截 | 删掉 `rule_set: geosite-category-ads-all` 的 `reject` 规则 |
| 允许 QUIC / HTTP/3 | 删掉 `{"network":"udp","port":443,"action":"reject"}` 规则 |
| 禁用本地/区域直连规则（全量走远端网关） | 删掉 Layer 2 的直连规则与 `REGIONAL_SAFETY_NET` |
| 更换本地直连 DNS（`dns-direct`） | 改 `dns.servers` 里 `dns-direct` 的 `server`（默认 `223.5.5.5`） |
| 用 TUN 模式 | 把 `inbounds` 的 `mixed` 换成 `tun`，`stack` 建议用 `system`（`gvisor`/`mixed` 在部分 macOS 客户端上会刷 socket 错误） |
| 双节点分流 | 见 [双节点 + 智能分流](DUAL-NODE.md) |

修改后务必 `sing-box check -c <文件>` 验证，通过再下发。

---

## 双节点模式下的差异

启用 `--with-aggregator` 时由同一份 `build_profile.py` 渲染双节点配置，规则层级相同，并在服务优先级层加入：

```
服务按域名选路（RESI_PRIORITY_DOMAINS / DC_DOMAINS）
  ├─ OpenAI / Anthropic / Gemini / PayPal / TikTok 域名 → 住宅节点（🎯 Select，排在区域直连之前防止误分流）
  ├─ Telegram / Discord 域名与 IP 段                   → 数据中心节点（🏢 Datacenter）
  └─ 本地/区域直连域名与规则集                         → direct
```

注意：**`RESI_PRIORITY_DOMAINS` 排在区域规则集之前**防止核心 AI/支付/媒体域名被宽泛 GeoIP 误判直连；同时**常规本地/区域直连域名位于 `DC_DOMAINS` 与兜底规则之前**，保证本地站点直连、避免跨洋折返远端网关产生额外延迟。详见 [双节点 + 智能分流](DUAL-NODE.md)。

---

## 相关文档

- [新手完整教程](BEGINNER_GUIDE.md)
- [双节点 + 智能分流](DUAL-NODE.md)
- [客户端导入](CLIENTS.md)
- [故障排查](TROUBLESHOOTING.md)
- [English version](../en/ROUTING.md)
