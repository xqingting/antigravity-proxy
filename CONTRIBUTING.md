# Contributing to Antigravity Proxy

感谢你对 Antigravity Proxy 项目的关注与贡献！我们非常欢迎社区提交 Issue 和 Pull Request。

## 🛠️ 本地开发环境设置

1. **先决条件**：
   - Node.js 18+ 与 pnpm (`npm i -g pnpm`)
   - Python 3.10+
   - Rust 1.75+ 与 Cargo (`curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh`)
   - 官方 Antigravity CLI (`agy`) 已登录可用

2. **安装依赖**：
   ```bash
   pnpm install
   ```

3. **启动开发调试**：
   - 仅前端热重载：
     ```bash
     pnpm dev
     ```
   - 桌面客户端联调：
     ```bash
     pnpm tauri dev
     ```

4. **运行测试**：
   ```bash
   python3 test_client.py
   ```

## 📝 提交规范与 Pull Request 流程

1. Fork 本仓库并基于 `main` 创建新分支（例如 `feature/xxx` 或 `fix/xxx`）。
2. 保持代码清晰整洁，提交信息格式建议使用清晰的语义化前缀：
   - `feat: 增加对某个客户端或特性的支持`
   - `fix: 修复某平台下的启动问题`
   - `docs: 更新安装或配置说明`
3. 确保本地 `pnpm build` 与 `python3 -m py_compile agy_proxy.py` 检查通过。
4. 提交 PR 并简要描述改动背景及自测效果。
