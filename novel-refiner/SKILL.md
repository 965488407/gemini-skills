---
name: novel-refiner
description: Specialized workflow for refining Chinese web novels into colloquial video scripts. Use when the user asks to "refine novel", "精炼小说", "生成视频文案", "规划剧情块", or work with novel chapters in the workspace.
---

# Novel Refiner Skill

将网文转化为口语化视频解说文案的专业工作流。

## Capabilities

1. **项目初始化** - 清理工作区，智能分割大型小说文件为独立章节
2. **剧情规划** - 生成带情绪曲线和预知式钩子的剧情块规划
3. **文案精炼** - 将剧情块重写为"说书人"风格的视频文案

## Usage

使用 `scripts/novel_refiner.py` 脚本：

### 初始化（每本新书执行一次）
```bash
python .gemini/skills/novel-refiner/scripts/novel_refiner.py init
```
- 扫描 `小说原文/` 目录
- 分割大文件为章节
- 创建 `story_context.txt`

### 规划阶段
```bash
python .gemini/skills/novel-refiner/scripts/novel_refiner.py plan <起始章节> [章节数]
```
示例：`python .gemini/skills/novel-refiner/scripts/novel_refiner.py plan 1 50`

### 精炼阶段
```bash
python .gemini/skills/novel-refiner/scripts/novel_refiner.py refine <剧情块文件路径>
```
示例：`python .gemini/skills/novel-refiner/scripts/novel_refiner.py refine "剧情块/规划_B1_第1-8章.txt"`

## Directory Structure

脚本假设从项目根目录运行：
- `小说原文/` - 源文本
- `剧情块/` - 剧情规划输出
- `精炼成品/` - 最终文案输出
- `story_context.txt` - 剧情状态表

## Workflow

1. 放入小说原文 → 运行 `init`
2. 运行 `plan` 生成剧情块规划 JSON
3. 将规划保存到 `剧情块/` 目录
4. 运行 `refine` 生成视频文案
5. 更新 `story_context.txt` 后继续下一块

## Assets

- `assets/剧情块提示词.txt` - 规划阶段提示词模板
- `assets/小说精炼提示词.txt` - 精炼阶段提示词模板
- `assets/设定提取提示词.txt` - 设定提取提示词
- `assets/story_context_template.txt` - 状态表模板
- `assets/SOP.txt` - 完整操作流程文档
