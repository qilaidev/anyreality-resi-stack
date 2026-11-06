# 客户端导入 | Client import

> **默认协议是 `vless-reality`（VLESS + REALITY + Vision），两个生态都能用。** 可选的
> `--protocol anytls-reality` 填充更强，但 mihomo 无法表达该节点，因此**不生成 Clash 订阅**。
> 完整论证：[README 协议选型](../../README.md#协议选型为什么默认不是-anyreality)。

安装完成后，服务器会给你一个订阅 URL（如果启用了 `--with-subscription`），完成卡上还会有一条
`vless://` 分享链接。

**一个订阅 URL 服务两个生态**：服务端按 User-Agent 决定返回 sing-box `profile.json` 还是
Clash `profile.yaml`。想指定格式就在 URL 后面直接写文件名，例如 `http://<IP>/<TOKEN>/profile.yaml`。

> 🔴 **优先用订阅 URL，不要只导入那条 `vless://`。**
> 分享链接只描述「直连 REALITY」**一条路径**，拿不到 Hysteria2、CDN 中转、备用端口，
> 也拿不到自动选路和内嵌的分流规则 —— 而在国内，单一路径必然会在某条线路上失效。
> 另外，以后改节点、加节点、换 IP，订阅一键同步；手动粘贴的客户端要全手动改。

---

## 哪些客户端能用（默认协议 `vless-reality`）

- **sing-box 系**：sing-box 官方 App（SFA Android / SFI iOS / SFM macOS）、Karing、Hiddify、
  NekoBox / nekoray。拿到 `profile.json`，三条路径与自动选路齐全。
- **Clash 系**：Clash Verge / Verge Rev、mihomo / Clash.Meta、Stash、走 Clash 订阅的 Shadowrocket。
  拿到 `profile.yaml`，同样包含三条路径（CDN 节点关闭 smux —— mihomo 在这条路上约每 5 分钟掉一次）。

> **只有 `--protocol anytls-reality` 会缩小这个范围**：mihomo 的 `anytls` 块没有 `reality-opts`，
> 那个节点写不出来，所以该模式下**根本不生成 Clash 订阅**（而不是生成一份残缺的）。

---

## 各客户端最低支持版本（Clash 系）

> 下表针对 Clash 系客户端。sing-box 系见下面「sing-box 系客户端」一节。
> 想让 Hysteria2 路径也可用，mihomo 需要 1.16+（`hysteria2` + `obfs: salamander`）。

| 客户端 | 平台 | 最低版本 | 支持 Reality | 支持 xtls-rprx-vision | 支持流量卡片 |
|---|---|---|---|---|---|
| v2rayN | Windows | 6.0+ | ✓ | ✓ | ✓ |
| Clash Verge / Verge Rev | Win/Mac/Linux | 1.4+ | ✓ | ✓ | ✓ |
| Stash | iOS/Mac | 2.5+ | ✓ | ✓ | ✓ |
| sing-box 客户端 | All | 1.7+ | ✓ | ✓ | 部分 |
| Hiddify | All | 2.0+ | ✓ | ✓ | ✓ |
| Streisand | iOS | 2024+ | ✓ | ✓ | ✓ |
| Shadowrocket | iOS | 2.2+ | ✓ | ✓ | ✓ |
| v2rayNG | Android | 1.8+ | ✓ | ✓ | ✓ |
| NekoBox | Android | 1.3+ | ✓ | ✓ | ✓ |

⚠️ 老版本 Clash for Windows、ClashX 不支持 Reality，必须换 Verge 系或 Stash。

---

## Windows · v2rayN

1. 下载最新版 [v2rayN](https://github.com/2dust/v2rayN/releases)
2. 打开 → `订阅` → `订阅设置` → `添加`
3. 填：
   - 备注：`anyreality-resi-stack`
   - 地址：你的订阅 URL（`http://你的服务器/你的token`）
4. 确定 → 右键节点 → `订阅` → `更新订阅`
5. 选中节点 → `Ctrl+T` 测延迟
6. 系统代理 → `自动配置系统代理`

---

## Mac · Clash Verge Rev

1. 下载 [Clash Verge Rev](https://github.com/clash-verge-rev/clash-verge-rev/releases)
2. 安装 → 打开 → `配置` 标签
3. 粘贴订阅 URL → `下载`
4. 选中刚下载的配置 → 启用
5. 顶部菜单 `Outbound Mode` 选 `Rule`
6. 系统代理：右上角菜单 → `System Proxy` 打开

---

## iOS · Stash（推荐，付费）

1. App Store 搜 Stash 安装
2. 打开 → `配置` → 右上角 `+` → `URL` → 粘贴订阅 URL
3. 等下载完成 → 选中配置 → 启用
4. 顶部主页 → 拖一下底部开关启动 VPN

---

## iOS · Shadowrocket（付费 + 国区不可用）

1. 复制 vless:// 链接到剪贴板
2. 打开 Shadowrocket → 主页右上角 `+` → 自动检测剪贴板
3. 或：`服务器` 标签 → 右上角 `+` → `订阅` → 粘贴订阅 URL

---

## Android · v2rayNG / NekoBox

1. v2rayNG / NekoBox 装最新版
2. 主页右上角 `+` → `从剪贴板导入配置`（贴 vless://）
   - 或：`设置` → `订阅设置` → 添加订阅 URL → 更新
3. 选中节点 → 主页底部启动按钮

> 注：`vless://` 分享链接只包含直连 REALITY 一条路径，没有 Hysteria2、CDN 中转和自动选路。完整能力请用订阅 URL。

---

## sing-box 系客户端（推荐）

sing-box 官方 App（SFA / SFI / SFM）、Karing、Hiddify、NekoBox 等都能直接导入默认订阅返回的 sing-box `profile.json`。

**订阅方式（推荐）：**

1. App Store / Play / GitHub Releases 装 sing-box 官方 App（或 Karing / Hiddify / NekoBox）
2. `配置` → 新建 → 选订阅 URL 类型，粘贴你的订阅 URL
3. 更新订阅 → 主页启动

默认订阅返回的就是完整 sing-box JSON（`profile.json`），无需再手动改 schema。

**手动导入（仅在不走订阅时；这样只拿得到这一条路径）：** 下列字段对应 `--protocol anytls-reality`：

`配置` → 新建 → 按下面字段手填一个 `anytls` outbound（用你自己的真实值）：

- `type` = `anytls`
- `server` = 你的服务器 IP
- `port`（`server_port`）= 入站端口
- `password` = `<ANYTLS_PASSWORD>`（AnyReality 用密码认证，无 UUID / flow）
- `tls.server_name` = `<SNI>`
- `tls.utls.fingerprint` = `chrome`
- `tls.reality.public_key` = `<REALITY_PUBLIC_KEY>`
- `tls.reality.short_id` = `<SHORT_ID>`

完整可参考的示例配置见 `examples/single-node/sing-box-client-config.json`。

---

## 验证客户端确实在用你的节点

打开浏览器访问 [https://ipinfo.io](https://ipinfo.io)，应看到：

- IP 是你 VPS 的公网 IP
- ASN 标记你 VPS 所属的 ISP
- 地理位置是你 VPS 所在城市

如果显示的是你本地真实 IP，说明客户端没有把流量送到代理。检查：

- 客户端是否打开了"系统代理"或 TUN 模式
- 浏览器是否在用客户端代理（macOS/Linux 上 Firefox 默认不跟随系统代理，要手动设）
- 客户端规则是否把这个域名匹到了 DIRECT

---

## 验证 OpenAI/ChatGPT 链路可用（住宅 IP 的价值点）

```bash
curl -i https://api.openai.com/v1/models
```

预期返回 `HTTP/2 401`（没有 API key 当然 401，但**这代表 OpenAI 接受了你的 IP**）。如果返回 `403 Country, region, or territory not supported`，说明 OpenAI 拒绝了你的出口 IP —— 通常意味着 IP 段被识别为非住宅、或者本身在屏蔽列表。

---

## 双节点客户端的导入差异

双节点部署后，订阅 URL 返回的配置（sing-box `profile.json` 或 Clash `profile.yaml`，按 User-Agent 选）已经包含**两个节点 + 智能分流规则**。客户端导入流程跟单节点完全一样，**不需要任何额外配置**。

导入后客户端会自动看到：

- 2 个节点（如 `US-Resi-01` 和 `US-DC-01`）
- 3 个 proxy group：`RESI`、`DC`、`AUTO`
- 一套已经写好的 rules（TG → DC、OpenAI → RESI、其它 → AUTO）

如果想手动覆盖某条规则，直接在客户端的"规则集"里改即可，不需要回到服务端动 YAML。

---

## 出现问题？

- 第一次部署不知道从哪开始 → [BEGINNER_GUIDE.md](BEGINNER_GUIDE.md)
- 客户端不显示流量条 → [TROUBLESHOOTING.md](TROUBLESHOOTING.md) "订阅 URL 能打开" 小节
- 客户端连不上 → [TROUBLESHOOTING.md](TROUBLESHOOTING.md) "客户端连不上" 小节
- TG 上传慢 → [DUAL-NODE.md](DUAL-NODE.md) 或 [TROUBLESHOOTING.md](TROUBLESHOOTING.md) "TG / Discord" 小节
