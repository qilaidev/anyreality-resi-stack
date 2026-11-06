# 客户端分流规则 | Client routing rules

本页说明**客户端配置里的路由规则**：为什么需要它、规则分几层、怎么增删国内平台、怎么验证某个域名确实走了直连。

服务端的入站配置不做分流（`templates/singbox/03_route.json` 的 `final` 是 `direct`，节点只负责把流量放出去）。**所有分流决策都发生在客户端配置里**，也就是订阅下发的 `profile.json` / `profile.yaml`。

---

## 为什么必须有分流规则

如果你用的是**系统代理**模式，不配规则最多是国内网站绕一圈美国，慢但能用。

但用 **TUN / 虚拟网卡**模式时（sing-box 官方 App、Karing、Hiddify 的默认模式），系统所有流量都被内核劫持，**没有"全局 / 直连"开关可选 —— 流量走不走代理完全由规则决定**。规则不完善的直接后果：

- 访问淘宝、微信、B 站、银行 App 也被发往海外节点 → 慢、卡、验证码风控、部分银行直接拒绝
- 国内 DNS 被送到境外解析 → CDN 调度到海外机房，越用越慢
- 广告 / 追踪域名照常连通，白白消耗节点流量

所以本项目下发的客户端配置**默认自带完整分流规则**，导入即用，不需要你手动配置。

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

Layer 2  国内直连（两级）
  ├─ 显式安全网 domain_suffix 列表 → direct     ← 人工维护，内联在配置里
  ├─ rule_set geosite-cn          → direct     ← SagerNet 社区规则集
  └─ rule_set geoip-cn            → direct     ← SagerNet 社区规则集

Layer 3  兜底
  ├─ udp:443 → reject             拦 QUIC，逼浏览器回落 TCP
  └─ final   → 节点出站
```

### 为什么 Layer 2 要做两级

| | 显式安全网（内联） | `geosite-cn` 规则集 |
|---|---|---|
| 内容 | 约 60 个高频域名后缀，人工精选 | 数万条，社区综合维护 |
| 可见性 | 直接写在配置里，一眼能看清 | 二进制 `.srs`，黑盒 |
| 来源 | 本仓库模板 | `raw.githubusercontent.com` 远程下载 |
| 失效风险 | 无 | 下载失败 / 更新滞后 / GitHub 不可达 |

`geosite-cn` 覆盖面远大于安全网，但它**依赖首次启动时从 GitHub 下载成功**。首次连接前 GitHub 往往正好不可达，规则集为空，于是**所有国内网站都被送出国** —— 这是"刚导入订阅时特别卡"的最常见原因。

内联安全网不依赖任何网络请求，且排在 `geosite-cn` 之前，因此即使规则集没下载下来，微信、支付宝、淘宝、B 站、网银这类高频服务也一定是直连的。

> `download_detour` 已设为节点出站，规则集本身是**通过你的节点**下载的，所以只要节点通就能拉到。

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

完整列表以 [`scripts/build_profile.py`](../../scripts/build_profile.py) 里的 `CN_SAFETY_NET` 为准；渲染后的样例见 [`examples/single-node/sing-box-client-config.json`](../../examples/single-node/sing-box-client-config.json)。

---

## 增删国内平台

**改模板（影响后续所有安装）：**

```bash
# 1. 高频域名加进 build_profile.py 的 CN_SAFETY_NET（内联安全网，不依赖任何下载）；
#    国内 CDN 类域名加进 data/geosite-cn-extra.json 的 domain_suffix 数组
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
| 国内也走代理（境外用户） | 删掉 Layer 2 的三条 `direct` 规则 |
| 换国内 DNS | 改 `dns.servers` 里 `dns-direct` 的 `server`（默认 `223.5.5.5`） |
| 用 TUN 模式 | 把 `inbounds` 的 `mixed` 换成 `tun`，`stack` 建议用 `system`（`gvisor`/`mixed` 在部分 macOS 客户端上会刷 socket 错误） |
| 双节点分流 | 见 [双节点 + 智能分流](DUAL-NODE.md) |

修改后务必 `sing-box check -c <文件>` 验证，通过再下发。

---

## 双节点模式下的差异

启用 `--with-aggregator` 时下发的是 `client-dual.json.tmpl`，规则层级相同，只是在 Layer 2 和 Layer 3 之间多插了两组：

```
Layer 2.5  按服务选出口
  ├─ OpenAI / Anthropic / Gemini / Netflix 域名 → 住宅节点
  ├─ Telegram / Discord 域名                    → 数据中心节点
  └─ Telegram IP 段（91.108.x / 149.154.160.0/20）→ 数据中心节点
```

注意顺序：**国内直连在前，服务选路在后**。这样国内域名不会因为命中服务规则而被绕出国。详见 [双节点 + 智能分流](DUAL-NODE.md)。

---

## 相关文档

- [新手完整教程](BEGINNER_GUIDE.md)
- [双节点 + 智能分流](DUAL-NODE.md)
- [客户端导入](CLIENTS.md)
- [故障排查](TROUBLESHOOTING.md)
- [English version](../en/ROUTING.md)
