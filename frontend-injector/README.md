# Antigravity 对话实时统计状态栏插件 (Frontend Metrics Injector)

在 **Google Antigravity** 的对话输入框下方注入一个原生风格的统计信息栏，像素级复刻参考设计：

```text
6 轮 · 14 步  |  LLM 3m8s · 工具调用 26.7s  |  首 token 平均 1s · 94 tok/s  |  缓存命中 84%  |  输入 297K tok · 输出 16.2K tok
```

---

## ✨ 核心特性

1. **会话精准隔离 (Per-Conversation Isolation)**：
   * 自动感知每个项目、每个单独对话的切换。
   * 当从对话 A 切换到对话 B 时，瞬时读取对话 B 独有的 `transcript.jsonl` 日志，独立统计轮数、步数、Token 总量与速率，数据绝不串流。
2. **多维度核心指标全覆盖**：
   * **轮数 · 步数**：基于当前会话的交互轮数（User Input）与模型步骤（Planner + Tools）。
   * **LLM 耗时 · 工具耗时**：大模型生成消耗的时间与本地工具执行消耗的时间。
   * **首 Token 延迟 · 平均速率**：流式生成时秒级测速，生成结束后计算全会话平均 `tok/s`。
   * **缓存命中率**：基于当前多轮对话上下文膨胀计算出的估计命中比（如 `84%`）。
   * **输入 / 输出 Token 总量**：包含当前会话工程代码上下文预估与生成的总 Token 统计。
3. **原生视觉与主题自适应**：
   * 挂载在 `[data-testid="agent-input-box"]` 正下方。
   * 自适应 Antigravity 的深色（Dark）和浅色（Light）模式，柔和且不喧宾夺主。
   * 模型生成时带有呼吸微光指示。

---

## 🚀 两种使用方式（任选其一）

### 方式一：客户端一键注入（推荐，重启后常驻）

通过向客户端的 `preload.js` 写入外链钩子，直接引入本地脚本。

* **安装补丁**：
  ```bash
  cd "/Users/wadeliu/Desktop/通用项目/antigravity-proxy/frontend-injector"
  chmod +x patch_asar.sh unpatch_asar.sh
  ./patch_asar.sh
  ```
* **特点**：
  * 只需执行一次，后续每次启动 Antigravity 自动生效。
  * **热生效**：后续如果想自定义修改样式或算法，直接修改 `antigravity-metrics-bar.js` 即可，刷新客户端立即生效，**不需要重新打包**！
* **卸载还原**：
  ```bash
  ./unpatch_asar.sh
  ```

---

### 方式二：免修改客户端热注入（零改动，完全不怕更新）

利用 Antigravity 默认开启的本地 DevTools 调试通道进行热注入：

* **单次注入**：
  ```bash
  cd "/Users/wadeliu/Desktop/通用项目/antigravity-proxy/frontend-injector"
  node live_inject.js
  ```
* **后台守护进程（推荐）**：
  ```bash
  node live_inject.js --daemon
  ```
* **特点**：
  * 100% 不修改应用文件，不碰 Apple 签名。
  * 软件版本自动更新也不会被破坏，保持脚本在后台即可自动重新挂载。

---

## 📁 目录文件结构

* `antigravity-metrics-bar.js`：核心前端注入脚本（包含 DOM 渲染、测速计时器、日志直读解析器）。
* `live_inject.js`：通过 Chrome 调试协议的无侵入免修补热注入器。
* `patch_asar.sh`：一键解包打包注入脚本（自动备份与修复 macOS 代码签名）。
* `unpatch_asar.sh`：一键还原官方原始客户端脚本。
