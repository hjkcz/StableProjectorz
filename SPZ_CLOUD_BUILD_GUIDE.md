# SPZ 云构建指南（GitHub Actions）

## 概述

本指南说明如何通过 GitHub Actions 在云端构建 StableProjectorz Windows EXE。

构建分三个阶段，**必须按顺序执行**：

| 阶段 | build_type | 内容 | 前置条件 |
|------|-----------|------|---------|
| 1 | `activate` | 获取 Unity 许可证 | Unity 账号 |
| 2 | `baseline` | 原始工程基线构建 | `UNITY_LICENSE` secret |
| 3 | `cn` | 中文化 + CJK 字体 + Agent Bridge | baseline 通过 |

**不要跳过基线构建。** 基线构建验证工具链可用后，再进入 CN 构建。

## 架构说明

- **Runner**: `windows-latest`（GitHub 托管，预装 VS 2022 Build Tools + Windows SDK）
- **Unity**: 原生安装（非 Docker），避免 Docker 容器缺少 VC++ 工具链的问题
- **IL2CPP**: 通过 Unity 安装器的 TargetSupportInstaller 单独安装
- **不使用 game-ci/unity-builder**: 该 Action 依赖 Docker，Windows IL2CPP 在 Docker 中有 VC++ 限制。改为直接调用 `Unity.exe -batchmode`

## 前置条件

1. **GitHub 账号** — 免费版即可
2. **Unity 账号** — 注册 https://id.unity.com（免费 Personal 许可证）
3. **SPZ 源码 Fork** — 将 `IgorAherne/StableProjectorz` fork 到自己的 GitHub

## 需要提交到 Fork 的文件

以下文件必须提交到仓库：

| 文件 | 用途 |
|------|------|
| `.github/workflows/build-spz-windows.yml` | GitHub Actions 工作流（三阶段） |
| `Assets/Editor/SPZCloudBuild.cs` | Unity 构建脚本（场景收集 + IL2CPP + 字体 + Bridge） |
| `Assets/Editor/SPZCloudBuild.cs.meta` | Unity meta 文件（GUID 关联） |
| `tools/apply_cn_localization.py` | 中文化脚本（可复现执行） |
| `tools/translations.json` | 翻译数据（276 对 EN→CN） |
| `.gitignore`（修改版） | 确保构建文件不被忽略 |

**重要**：中文化 Prefab/Scene 变更**不需要提交**。CI 在构建前自动运行 `apply_cn_localization.py` 应用翻译，确保可复现。

## Step 1: Fork 仓库并提交构建文件

```bash
# Fork IgorAherne/StableProjectorz on GitHub
git clone https://github.com/<你的用户名>/StableProjectorz.git
cd StableProjectorz

# 复制构建文件
mkdir -p .github/workflows tools Assets/Editor
cp .github/workflows/build-spz-windows.yml .github/workflows/
cp Assets/Editor/SPZCloudBuild.cs Assets/Editor/
cp Assets/Editor/SPZCloudBuild.cs.meta Assets/Editor/  # 如果有
cp tools/apply_cn_localization.py tools/
cp tools/translations.json tools/

git add -A
git commit -m "Add cloud build: 3-phase workflow + CN localization + Agent Bridge"
git push origin main
```

## Step 2: 获取 Unity 许可证（仅一次）

### 2.1 运行 activate job

1. GitHub 仓库 → Actions → "Build SPZ Windows" → Run workflow
2. `build_type` 选择 `activate`
3. 等待完成，下载 artifact `unity-activation-file`

### 2.2 ALF → ULF 转换

**ALF ≠ ULF。** ALF 是激活请求文件，ULF 是许可证文件。

1. 下载 artifact 中的 `.alf` 文件
2. 打开 https://license.unity3d.com/manual
3. 上传 `.alf` 文件
4. 网站生成 `.ulf` 文件，下载

### 2.3 配置 GitHub Secrets

进入仓库 Settings → Secrets and variables → Actions，创建：

| Secret 名称 | 值 |
|-------------|---|
| `UNITY_LICENSE` | `.ulf` 文件的**完整内容**（XML 格式，直接粘贴） |
| `UNITY_EMAIL` | Unity 账号邮箱 |
| `UNITY_PASSWORD` | Unity 账号密码 |

**不要把 ULF 文件提交到仓库。** ULF 包含机器绑定信息，仅存为 Secret。

参考：https://game.ci/docs/github/activation

## Step 3: 基线构建

1. Actions → "Build SPZ Windows" → Run workflow
2. `build_type` 选择 `baseline`
3. 等待构建完成（首次约 30-50 分钟，含 Unity 安装）

### 基线构建验收

- [ ] Job 状态为 success
- [ ] Artifact `SPZ-Baseline-*` 已生成
- [ ] `BUILD_MANIFEST.txt` 中 `build_result: SUCCESS`
- [ ] `SHA256SUMS` 文件已生成
- [ ] 下载 EXE 可正常启动
- [ ] 界面为英文（基线不含中文化）

**基线通过后才能进入 Step 4。**

## Step 4: CN 构建（中文化 + Agent Bridge）

1. Actions → "Build SPZ Windows" → Run workflow
2. `build_type` 选择 `cn`
3. 等待构建完成

### CN 构建验收清单

| 验收项 | 方法 | 通过标准 |
|--------|------|---------|
| 构建成功 | Job status + manifest | `build_result: SUCCESS` |
| 构建清单 | `BUILD_MANIFEST.txt` | 含 commit、版本、场景列表、字体哈希 |
| 文件校验 | `SHA256SUMS` | 所有关键文件有 SHA-256 |
| 启动验证 | 运行 `StableProjectorz-CN.exe` | 程序正常启动，无崩溃 |
| 中文验证 | 检查界面文字 | 无豆腐块（□□□），无明显截断 |
| 中文输入 | 在提示词框输入中文 | 可输入并显示中文 |
| Bridge 验证 | 见下方 | 已认证请求成功返回 |
| 投影验证 | 测试图→投射→导出 | 见下方 |

### Agent Bridge 验证

```powershell
# 1. 启动程序后，验证端口
Test-NetConnection -ComputerName 127.0.0.1 -Port 8765
# 应返回 TcpOpen : True

# 2. 使用 token 调用 describe（不能只检查端口）
$token = "change-me"  # spz.config 中的 --agent-bridge-token 值
$response = Invoke-RestMethod -Uri "http://127.0.0.1:8765/describe" -Headers @{ "Authorization" = "Bearer $token" }
$response | ConvertTo-Json
# 应返回应用状态信息

# 3. 调用 get_app_state
$appState = Invoke-RestMethod -Uri "http://127.0.0.1:8765/get_app_state" -Headers @{ "Authorization" = "Bearer $token" }
$appState | ConvertTo-Json
```

### 投影验证

**注意**：停止假 A1111 服务器后再启动真实代理。两者都用 `7860` 端口，不能同时运行。

```bash
# 1. 停止假服务（如果在运行）
# Ctrl+C 停止 fake_a1111_server.py

# 2. 启动真实代理
export OPENAI_API_KEY=sk-xxx
python gpt_image_proxy.py  # 监听 7860

# 3. SPZ 连接代理（127.0.0.1:7860）
# 4. 加载测试模型
# 5. 单视角投射测试
# 6. 导出投射结果
# 7. 验证导出图片正确
```

## 构建产物内容

```
StableProjectorz-CN/
├── StableProjectorz-CN.exe        # 主程序（含 Agent Bridge 代码）
├── StableProjectorz-CN_Data/      # 数据目录
├── GameAssembly.dll               # IL2CPP 编译的程序集
├── global-metadata.dat            # IL2CPP 元数据
├── spz.config                     # 配置文件（Agent Bridge 已启用）
├── BUILD_MANIFEST.txt             # 构建清单
└── SHA256SUMS                     # 文件校验
```

## 故障排查

### 构建失败：Unity License 错误
- 检查 `UNITY_LICENSE` Secret 是否为 ULF 文件的完整内容
- ULF 文件是 XML 格式，以 `<?xml` 开头
- 确认 `UNITY_EMAIL` 和 `UNITY_PASSWORD` Secret 正确
- 参考 https://game.ci/docs/github/activation

### 构建失败：Unity 安装失败
- 检查 `UNITY_VERSION` 和 `UNITY_CHANGESET` 是否匹配
- 验证 changeset: https://unity.com/releases/editor/whats-new/6000.2.6
- 下载链接格式: `https://download.unity3d.com/download_unity/<changeset>/...`

### 构建失败：IL2CPP 编译错误
- 查看 `SPZ-CN-logs-*` artifact 中的 `unity_build.log`
- 确认 Windows SDK 和 VS Build Tools 可用（windows-latest 预装）
- 检查 `build_errors.txt` 中的具体错误

### 中文化显示为豆腐块（□□□）
- 检查构建日志中 `[CJK]` 相关输出
- 确认 `cjk_font_sha256` 在 manifest 中匹配
- 确认 `cjk_fallback_verified: true` 在 manifest 中

### CN 脚本执行失败
- 检查 `tools/translations.json` 是否存在且格式正确
- 本地测试: `python tools/apply_cn_localization.py --translations tools/translations.json --repo . --verify`
- 确保 276 对翻译全部存在

### Agent Bridge 端口未监听
- 检查 manifest 中 `agent_bridge: ENABLED` 和 `agent_bridge_verified: true`
- 检查 `spz.config` 中 `--agent-bridge` 行未被注释
- 查看程序日志确认 Agent Bridge 启动消息

## 关于构建时间与资源

以下数据为**估算值**，实际值以构建结果为准：

| 项目 | 估算值 |
|------|--------|
| Unity 安装 | 10-15 分钟 |
| 首次构建（无缓存） | 30-50 分钟 |
| 后续构建（有缓存） | 15-25 分钟 |
| 构建产物大小 | 待实测 |
| GitHub Actions 免费额度 | 2000 分钟/月（Windows runner 消耗倍率为 2x） |

**注意**：Windows runner 的 Actions 分钟数消耗倍率为 2x，即 1 分钟实际运行 = 2 分钟配额。

## 文件索引

| 文件 | 位置 | 说明 |
|------|------|------|
| 工作流 | `.github/workflows/build-spz-windows.yml` | 三阶段 GitHub Actions |
| 构建脚本 | `Assets/Editor/SPZCloudBuild.cs` | Unity Editor 构建逻辑 |
| 中文化脚本 | `tools/apply_cn_localization.py` | 可复现的翻译应用工具 |
| 翻译数据 | `tools/translations.json` | 276 对 EN→CN 翻译 |
| 假 A1111 服务器 | `F:\bolod\obsidian\Note\🎃pubg\fake_a1111_server.py` | 本地协议验证 |
| GPT Image 代理 | `F:\bolod\obsidian\Note\🎃pubg\gpt_image_proxy.py` | 本地 API 代理 |
