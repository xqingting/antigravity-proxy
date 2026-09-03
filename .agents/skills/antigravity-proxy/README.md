# Antigravity Proxy Skill 🤖

**Google Antigravity 官方标准扩展技能包（Antigravity Agent Skill）**

用于在 Google Antigravity / Gemini CLI 中自动管理、测试与对接 **Antigravity Proxy** 本地 OpenAI 兼容代理服务。

---

## 📦 安装方法 (Installation)

### 方式 1：全局安装（推荐，所有项目生效）
将本技能克隆到用户全局技能配置目录：

```bash
mkdir -p ~/.gemini/config/skills
git clone https://github.com/xqingting/skill-antigravity-proxy.git ~/.gemini/config/skills/antigravity-proxy
```

### 方式 2：项目工作区安装（仅当前项目生效）
进入任意需要使用的项目根目录：

```bash
mkdir -p .agents/skills
git clone https://github.com/xqingting/skill-antigravity-proxy.git .agents/skills/antigravity-proxy
```

---

## 🚀 技能功能与触发方式

安装完成后，Antigravity AI Agent 将自动具备以下能力，在对话中直接自然语言吩咐即可：

- **服务启停管理**：“帮我启动 / 重启 / 停止 Antigravity Proxy”
- **运行状态检查**：“检查一下当前本地代理运行是否正常，累计消耗了多少 Token？”
- **客户端对接指导**：“我想把 Cursor / Continue / NextChat 接入本地 Antigravity，怎么配置？”
- **连通性与速率测试**：“测试一下代理的流式响应和生成速率 TPS”
- **故障排查诊断**：“代理端口被占用了 / 报错 429 怎么解决？”

---

## 📂 技能结构规范

```text
skill-antigravity-proxy/
├── SKILL.md                          # 核心定义与操作指南 (YAML Frontmatter)
├── references/
│   ├── client_integrations.md        # 各大客户端与 IDE 对接 cheatsheet
│   ├── api_reference.md              # OpenAI API 兼容端点详尽文档
│   └── architecture_and_security.md  # 0 封号风险原理与并发模型
├── scripts/
│   ├── status.sh                     # 快速状态健康探针
│   ├── start.sh                      # 智能启动脚本
│   ├── stop.sh                       # 安全停止脚本
│   └── test.sh                       # 快速请求测试
├── README.md
└── LICENSE
```

---

## 📄 开源协议

基于 [MIT License](LICENSE) 开源发布。
