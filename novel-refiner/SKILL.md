---
name: novel-refiner
description: Specialized workflow for refining Chinese web novels into colloquial video scripts. Use when the user asks to "refine novel", "精炼小说", "生成视频文案", "规划剧情块", "扫描高光点", or work with novel chapters in the workspace.
---

# Novel Refiner Skill

将网文转化为口语化视频解说文案的专业工作流。

## 核心理念：高光点锚定法

不是从头到尾顺序切分，而是：
1. **先找高光点** —— 找出最精彩的剧情节点
2. **以高光点为锚点** —— 向前找铺垫，向后找收尾
3. **形成完整剧情块** —— 每个块都有明确的高潮点

## 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│                    Novel Refiner 工作流                      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  [init] ──────────────────────────────────────► Claude      │
│    │     分割章节、创建目录（不需要大上下文）                  │
│    ▼                                                        │
│  [scan] ─────────────────────────────────────► Gemini Flash │
│    │     读取20-30章原文，输出高光点JSON                      │
│    │     (上下文窗口大，处理大量原文，便宜)                    │
│    ▼                                                        │
│  [plan] ─────────────────────────────────────► Gemini Flash │
│    │     读取高光点+原文，输出剧情块规划                      │
│    │     (上下文窗口大，处理大量原文，便宜)                    │
│    ▼                                                        │
│  [refine] ────────────────────────────────────► Gemini Pro  │
│           读取单个剧情块原文，输出精炼文案                    │
│           (写作质量高，处理较少原文)                          │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## 模型分配

| 阶段 | 模型 | 执行方式 | 原因 |
|------|------|---------|------|
| init | Claude | 直接 bash | 简单操作 |
| scan | Gemini Flash | `delegate_task(category="novel-scan")` | 大上下文、便宜 |
| plan | Gemini Flash | `delegate_task(category="novel-scan")` | 大上下文、便宜 |
| refine | Gemini 3 Pro | **Gemini CLI** (`gemini --yolo`) | 写作质量高、直接调用更省钱 |

## Usage

### 初始化（每本新书执行一次）
```bash
python .claude/skills/novel-refiner/scripts/novel_refiner.py init
```
- 扫描 `小说原文/` 目录
- 分割大文件为章节
- 创建 `story_context.txt`

### 高光点扫描
```bash
python .claude/skills/novel-refiner/scripts/novel_refiner.py scan <起始章节> [章节数]
```

**输出 JSON 任务描述**，包含：
- 提示词模板路径
- 章节文件路径列表
- 输出文件路径
- delegate_task 配置

**执行方式**：
```python
# 1. 运行脚本获取任务描述
task = json.loads(脚本输出)

# 2. 委托给 Gemini Flash 执行
delegate_task(
    category="novel-scan",
    load_skills=["novel-refiner"],
    prompt=f"""
执行高光点扫描任务。

1. 读取提示词模板：{task['files']['prompt_template']}
2. 读取以下章节文件并扫描高光点：
{chr(10).join(task['files']['chapter_files'])}

3. 输出 JSON 格式的高光点列表，保存到：{task['output']['file']}
"""
)
```

### 剧情块规划
```bash
python .claude/skills/novel-refiner/scripts/novel_refiner.py plan <起始章节> [章节数]
```

**执行方式**：同上，使用 `category="novel-scan"`

### 文案精炼（使用 Gemini CLI）

**⚠️ 重要：refine 阶段必须由主 agent 直接执行 bash 命令，不能 delegate_task！**

子 agent 环境中没有 Gemini CLI，所以 refine 必须这样执行：

```python
# 正确做法：主 agent 直接用 bash 工具执行
bash("python .claude/skills/novel-refiner/scripts/novel_refiner.py refine-exec '剧情块/规划_第1-30章.json'")

# 错误做法：不要 delegate_task 给子 agent
# delegate_task(category="novel-writing", ...)  # ❌ 子 agent 没有 gemini CLI
```

**一键执行命令**：
```bash
python .claude/skills/novel-refiner/scripts/novel_refiner.py refine-exec "剧情块/规划_第1-30章.json"
```

可选参数：指定处理特定块
```bash
python .claude/skills/novel-refiner/scripts/novel_refiner.py refine-exec "剧情块/规划_第1-30章.json" --block B1
```

这个命令会：
1. 自动读取所有需要的文件（提示词、剧情块规划、状态表、原文）
2. 构建完整提示词
3. 调用 `gemini --yolo` 执行
4. Gemini 3 Pro 会自动将结果保存到 `精炼成品/` 目录

**为什么用 Gemini CLI 而不是 delegate_task？**
- 直接调用 Gemini 3 Pro API，省去中间层开销
- 成本更低（不经过 OpenCode 的 token 计费）
- Gemini CLI 的 `--yolo` 模式自动批准文件读写操作

## Directory Structure

脚本假设从项目根目录运行：
- `小说原文/` - 源文本（分割后的章节）
- `剧情块/` - 高光点扫描结果 + 剧情规划输出
- `精炼成品/` - 最终文案输出
- `story_context.txt` - 剧情状态表

## Workflow（推荐流程）

```
1. 放入小说原文 → 运行 init (Claude)
         ↓
2. 运行 scan → delegate_task(category="novel-scan") (Gemini Flash)
         ↓
3. 重复 scan 直到覆盖所有章节
         ↓
4. 运行 plan → delegate_task(category="novel-scan") (Gemini Flash)
         ↓
5. 运行 refine → gemini --yolo (Gemini 3 Pro via CLI)
         ↓
6. 更新 story_context.txt，继续下一块
```

## Assets

- `assets/高光点扫描提示词.txt` - 高光点扫描阶段提示词
- `assets/剧情块提示词.txt` - 规划阶段提示词（基于高光点）
- `assets/小说精炼提示词.txt` - 精炼阶段提示词
- `assets/设定提取提示词.txt` - 设定提取提示词
- `assets/story_context_template.txt` - 状态表模板
- `assets/SOP.txt` - 完整操作流程文档

## 关键改进

### 为什么不直接输出原文？

旧版本的问题：
- `scan`/`plan`/`refine` 命令会把原文拼接到 prompt 中输出
- 30章原文 = 几十万字 → 超过 bash 输出限制 → 被截断

新版本的改进：
- 脚本只输出 **JSON 任务描述**（文件路径列表）
- 代理自己读取原文文件
- 不会截断，支持任意长度的小说

### 为什么用不同模型？

| 模型 | 优势 | 用途 |
|------|------|------|
| Gemini Flash | 上下文窗口大、便宜 | scan/plan（需要读大量原文） |
| Gemini 3 Pro (CLI) | 写作质量高、直接调用省钱 | refine（需要高质量输出） |
| Claude | 通用能力强 | init、协调、其他任务 |

### 为什么 refine 用 Gemini CLI？

1. **成本优势**：直接调用 Google API，不经过 OpenCode 中间层
2. **模型一致**：确保使用你配置的 Gemini 3 Pro（`~/.gemini/settings.json`）
3. **自动化**：`--yolo` 模式自动批准所有文件操作，无需人工确认
4. **简单可靠**：管道方式调用，输入提示词 → 输出结果 → 写入文件
