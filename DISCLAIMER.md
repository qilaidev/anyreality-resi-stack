# 法律合规、授权使用边界与免责声明 | Legal Compliance, Acceptable Use & Disclaimer

> [!IMPORTANT]
> **阅读与使用前提 / Mandatory Condition of Use**  
> 下载、复制、审阅、修改或运行本仓库（`anyreality-resi-stack`）中的任何脚本、模板或文档，即表示您已完整阅读、理解并无条件同意受本声明全部条款约束。若您不同意本声明，或您所在司法管辖区的法律法规禁止您部署或使用此类软件，请立即停止一切下载、部署与使用行为并销毁本地副本。

---

## 一、中文合规与免责声明（Chinese Legal & Compliance Notice）

### 1. 项目技术性质界定（纯配置自动化脚本，非网络接入服务）

1. **纯基础设施即代码（IaC）属性**：`anyreality-resi-stack` 仅包含面向开源通用网络转发引擎 [sing-box](https://sing-box.sagernet.org/)、Linux 系统基础组件（`systemd`、`sysctl`、`ufw`、`iptables`、`fail2ban`、`nginx`）及 Python 标准库的**本地配置渲染模板、运维自检脚本与格式转换工具**。
2. **零资源与零托管声明**：本项目开发者与维护者**不提供、不销售、不租借、不分发、不托管、不代维**任何云服务器（VPS）、静态住宅 IP、数据中心带宽、域名、TLS 证书、现成节点凭据或付费订阅服务。
3. **无中心化控制端与商业变现模块**：本仓库代码不包含任何多租户管理后台、计费配额结算系统、公共节点池、远程遥测回传或中心化控制平面；每次部署均由使用者在其完全自有的服务器上独立生成本机随机密钥。

### 2. 正当工程用途与授权使用场景

本项目旨在为**合法合规的网络工程研发与跨区域分布式基础设施运维**提供技术参考与自动化验证，正当适用场景严格限定为：

- **海外及跨国企业合规边缘接入**：位于允许自建加密隧道的境外司法管辖区，或已依法取得合法跨境专线/国际通信信道资质的跨国团队，用于远程研发运维、分支机构安全互联与分布式边缘网关管理；
- **广域网（WAN）弱网传输容灾研究**：针对高往返时延（High-RTT）、高丢包率、运营商级 NAT（CGNAT）会话回收、非对称路由抖动及中间盒（Middlebox）协议栈兼容性开展的多路径自动选路（TCP / QUIC / WebSocket）与内核拥塞控制（BBR / 套接字缓冲）工程测试；
- **海外业务本地化 QA 与 API 出口信誉隔离**：面向海外合规运营的 SaaS、AI 接口调用、流媒体及跨境支付测试环境，实施静态出口 IP 信誉保护、DNS/WebRTC 防旁路泄漏及双节点流量编排。

### 3. 司法管辖区合规红线与明确禁止条款

使用者必须自行核实并严格遵守其**人身所在地、国籍所属国、服务器物理所在地及目标服务所在地**的一切适用法律法规与电信监管规定：

1. **中国大陆地区特别合规要求**：
   位于中华人民共和国境内（不含港澳台地区）的任何个人或组织，必须严格遵守《中华人民共和国网络安全法》《中华人民共和国数据安全法》《中华人民共和国电信条例》以及《中华人民共和国计算机信息网络国际联网管理暂行规定》（特别是第六条“计算机信息网络直接进行国际联网，必须使用邮电部国家公用电信网提供的国际出入口信道。任何单位和个人不得自行建立或者使用其他信道进行国际联网”及第十四条）等法律法规：
   - **严禁非法跨境联网**：严禁任何未取得法定国际联网信道资质的境内个人或单位，利用本软件自行建立、租用或使用非法定信道进行国际联网，或用于规避国家网络安全监管与技术防护措施；
   - **境内仅限隔离实验与合规专线**：在中国大陆境内，本仓库代码仅限用于**不涉及非法跨境联网的本地局域网/虚拟实验室协议栈教学研究**，或由**持有合法国际通信出入口局专线/合规跨境 SD-WAN 资质的企业主体**在批准范围内进行内部运维自动化。
2. **严禁非法经营与多人共享**：严禁将本软件直接或改装后用于向第三方提供任何有偿或无偿的公共代理、VPN 租赁、节点转售、流量分销或多人共享接入服务。
3. **严禁违法犯罪与滥用行为**：严禁利用本软件从事任何未授权侵入或控制计算机信息系统、网络攻击（DDoS / 扫描渗透 / SSRF）、电信网络诈骗、洗钱、侵犯知识产权、非法数据爬取、传播违法违规信息或违背公序良俗的活动。

### 4. 担保免除与开发者零法律责任声明

1. 本仓库全部源代码与技术文档均依据 [GNU General Public License v3.0 (GPL-3.0)](LICENSE) 协议按**“原样（AS IS）”**公开发布，不附带任何明示或暗示的适销性、特定用途适用性、持续可用性或合规性担保。
2. 开发者对任何第三方的下载、修改、部署或运行行为**不知情、不参与、不控制、不获利**。
3. 任何个人或组织违反本声明或违反适用法律法规使用本软件所引发的一切行政处罚、民事索赔、刑事责任、账号封禁或商业损失，均由**使用者本人独立承担全部法律后果**，本项目开发者与代码贡献者概不承担任何直接、间接或连带责任。

---

## II. English Legal Compliance, Acceptable Use & Disclaimer

### 1. Nature of the Software (Configuration Automation Only)

1. **Pure Infrastructure-as-Code (IaC)**: `anyreality-resi-stack` consists solely of declarative configuration templates, Linux system administration scripts (`systemd`, `sysctl`, `ufw`, `iptables`, `fail2ban`, `nginx`), and zero-dependency Python standard-library profile formatters for the upstream open-source [sing-box](https://sing-box.sagernet.org/) networking engine.
2. **No Hosted Infrastructure or Transit**: The author(s) and maintainers **do not** sell, lease, host, operate, distribute, or broker any VPS instances, residential IP addresses, bandwidth, proxy nodes, domains, TLS certificates, or paid subscriptions.
3. **Single-Owner Architecture & Zero Telemetry**: By architectural design, this repository implements no multi-tenant user management, no billing or quota resale panel, no shared node pool, and no central control plane or telemetry. Cryptographic keys are generated locally on user-owned hosts at install time.

### 2. Intended & Authorized Engineering Use

This toolkit is published strictly for **lawful network engineering research and authorized self-hosted edge infrastructure administration**, including:

- **Authorized Cross-Region DevOps & Edge Gateways**: Deploying authenticated encrypted transport tunnels on user-owned servers in jurisdictions where self-hosted edge gateways are lawful, or over authorized enterprise international leased lines;
- **WAN Transport Resilience & Protocol Interoperability Research**: Studying uncorrelated transport failure modes (TCP vs. UDP/QUIC vs. reverse-proxied WebSocket), high-BDP socket buffer tuning, CGNAT mapping timeouts, and deterministic client configuration validation on lossy wide-area links;
- **Overseas Localization QA & Egress IP Hygiene**: Managing dedicated static egress reputation, preventing unintended WebRTC/DNS split-tunnel leaks, and orchestrating dual-node traffic routing for authorized SaaS/API testing.

### 3. Regulatory Compliance & Strictly Prohibited Uses

Users are solely responsible for ensuring that their deployment and use of this software comply with all laws and telecommunications regulations of **their physical location, nationality, server jurisdiction, and target service jurisdiction**:

1. **Telecommunications & Cross-Border Networking Laws (Including PRC Notice)**:
   Users located in jurisdictions that regulate international network interconnections — including Mainland China under the *Cybersecurity Law of the PRC*, *Data Security Law of the PRC*, *Telecommunications Regulations of the PRC*, and the *Interim Provisions on the Administration of International Networking of Computer Information Networks* (Articles 6 and 14) — **MUST NOT** use this software to establish unauthorized cross-border communication channels, bypass national network regulatory controls, or operate unlicensed telecommunications/VPN/proxy services. Within such jurisdictions, access to this repository is restricted to isolated local-lab protocol research or entities holding lawful international networking authorizations.
2. **No Commercial Resale or Public Sharing**: Using or modifying this toolkit to operate commercial proxy services, multi-user resale platforms, or public shared nodes is strictly prohibited.
3. **No Unlawful Conduct**: You may not use this software in connection with unauthorized system intrusion, cyberattacks, fraud, money laundering, unlawful data harvesting, copyright infringement, or violation of third-party terms of service.

### 4. "AS IS" Warranty & Limitation of Liability

This software is provided **"AS IS"** under the [GPL-3.0 License](LICENSE), without warranty of any kind, express or implied. The developer(s) and contributors have zero visibility into or control over third-party deployments, derive no benefit from third-party network transit, and assume **zero civil, administrative, or criminal liability** for any misuse, misconfiguration, or unlawful act committed by any user.
