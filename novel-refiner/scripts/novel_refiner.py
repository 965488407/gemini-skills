import os
import re
import json
import shutil
import argparse
import subprocess
from pathlib import Path
from datetime import datetime

class NovelRefiner:
    def __init__(self, root_dir="."):
        self.root = Path(root_dir).resolve()

        # 动态定位 skill 目录
        self.skill_dir = self._find_skill_dir()

        self.dirs = {
            "source": self.root / "小说原文",
            "blocks": self.root / "剧情块",
            "output": self.root / "精炼成品",
            "config": self.skill_dir / "assets",
            "archive": self.root / "_archive",
        }
        self.context_file = self.root / "story_context.txt"
        self.encoding_candidates = ["utf-8", "gbk", "gb18030", "utf-16"]

    def _find_skill_dir(self):
        """动态定位 skill 目录，支持多种部署位置"""
        possible_paths = [
            # Claude Code 路径
            self.root / ".claude" / "skills" / "novel-refiner",
            Path.home() / ".claude" / "skills" / "novel-refiner",
            # Gemini CLI 路径 (兼容)
            self.root / ".gemini" / "skills" / "novel-refiner",
            Path.home() / ".gemini" / "skills" / "novel-refiner",
            # 相对于脚本位置
            Path(__file__).parent.parent,
        ]
        for path in possible_paths:
            if (path / "SKILL.md").exists():
                return path
        # 回退到脚本所在目录的父目录
        return Path(__file__).parent.parent

    def _read_file(self, path):
        """Reads a file trying multiple encodings."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        for enc in self.encoding_candidates:
            try:
                return path.read_text(encoding=enc)
            except UnicodeDecodeError:
                continue
        raise ValueError(f"Could not read file {path} with supported encodings.")

    def _log(self, msg):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

    def clean_content(self, content):
        """
        Cleans content by removing ads and control characters.
        """
        ad_keywords = ['Fanqie-novel-Downloader', '免费下载器下载']

        lines = content.splitlines()
        cleaned_lines = []
        removed_count = 0

        for line in lines:
            if any(kw in line for kw in ad_keywords):
                removed_count += 1
                continue
            cleaned_lines.append(line)

        content = "\n".join(cleaned_lines)

        # Remove Unicode control characters
        control_chars = re.compile(r'[\u200b-\u200f\u202a-\u202e\u2060-\u206f\u061c]')
        content = control_chars.sub('', content)

        if removed_count > 0:
            self._log(f"Removed {removed_count} lines containing ads.")

        return content

    def init_project(self):
        """Initializes the project: ensures folders exist, splits source files."""
        self._log("Initializing project...")
        self._log(f"Skill directory: {self.skill_dir}")

        # 1. Create directories
        for key, path in self.dirs.items():
            if key != "config":  # config 目录不需要创建
                path.mkdir(exist_ok=True, parents=True)

        # 2. Split source files if needed
        self._split_source_files()

        # 3. Check context file
        if not self.context_file.exists():
            template_path = self.dirs["config"] / "story_context_template.txt"
            if template_path.exists():
                shutil.copy(template_path, self.context_file)
                self._log("Created story_context.txt from template.")
            else:
                self._log(f"Warning: story_context_template.txt not found at {template_path}")
        else:
            self._log("story_context.txt already exists.")

        self._log("Initialization complete.")

    def _split_source_files(self):
        """Splits large text files in '小说原文' into chapters using robust regex."""
        if not self.dirs["source"].exists():
            self._log(f"Source directory not found: {self.dirs['source']}")
            return

        source_files = list(self.dirs["source"].glob("*.txt"))

        strategies = [
            # 古早中文数字：土=十, 廿=二十, 卅=三十, 卌=四十
            re.compile(r"(?:^|\n|\s)(第[零一二三四五六七八九十百千万土廿卅卌]+章[^\n]*)"),
            re.compile(r"(?:^|\n|\s)(第\d+章[^\n]*)"),
            re.compile(r"(?:^|\n|\s)((?:第[零一二三四五六七八九十百千万土廿卅卌]+|第\d+)[章节卷集部][^\n]*)"),
        ]

        for file_path in source_files:
            if re.search(r"第\d+-", file_path.name) or file_path.stat().st_size < 50 * 1024:
                continue

            self._log(f"Processing large file: {file_path.name}")
            raw_content = self._read_file(file_path)
            content = self.clean_content(raw_content)

            parts = []

            for pattern in strategies:
                matches = list(pattern.finditer(content))
                if len(matches) > 5:
                    self._log(f"Matched pattern: {pattern.pattern}")

                    if matches[0].start() > 0:
                        parts.append(("前言/序章", content[:matches[0].start()]))

                    for i, match in enumerate(matches):
                        start = match.start()
                        end = matches[i+1].start() if i + 1 < len(matches) else len(content)
                        title = match.group(1).strip()
                        body = content[start:end]
                        parts.append((title, body))
                    break

            if not parts:
                self._log(f"Warning: No chapters found in {file_path.name}. Skipping.")
                continue

            book_name = file_path.stem.replace(" ", "_")
            book_dir = self.dirs["source"] / book_name
            book_dir.mkdir(exist_ok=True)

            self.dirs["archive"].mkdir(exist_ok=True)
            archive_path = self.dirs["archive"] / f"raw_{file_path.name}"
            shutil.move(file_path, archive_path)

            count = 0
            for idx, (title, body) in enumerate(parts):
                seq_num = idx + 1
                num_str = f"{seq_num:04d}"
                safe_title = re.sub(r'[\\/*?:"<>|]', "", title[:30]).strip()
                filename = f"第{num_str}-{safe_title}.txt"
                (book_dir / filename).write_text(body, encoding="utf-8")
                count += 1

            self._log(f"Split {file_path.name} into {count} chapters in {book_dir}")

    def _get_chapter_files(self, start_chapter, count):
        """Helper to get chapter file paths within range (no char limit)."""
        all_chapters = []
        for f in self.dirs["source"].rglob("*.txt"):
            if re.match(r"第\d+-", f.name):
                all_chapters.append(f)

        def extract_num(path):
            m = re.search(r"第(\d+)-", path.name)
            return int(m.group(1)) if m else 999999

        all_chapters.sort(key=extract_num)

        target_files = []
        end_chapter_num = start_chapter

        potential_files = [f for f in all_chapters if extract_num(f) >= start_chapter]

        for f in potential_files:
            if len(target_files) >= count:
                break
            target_files.append(f)
            end_chapter_num = extract_num(f)

        return target_files, start_chapter, end_chapter_num

    def merge_chapters(self, start_chapter, end_chapter, output_name=None):
        """合并指定范围的章节文件为单个文件，返回合并后的文件路径"""
        all_chapters = []
        for f in self.dirs["source"].rglob("*.txt"):
            if re.match(r"第\d+-", f.name):
                all_chapters.append(f)

        def extract_num(path):
            m = re.search(r"第(\d+)-", path.name)
            return int(m.group(1)) if m else 999999

        all_chapters.sort(key=extract_num)

        # 过滤范围
        selected = [f for f in all_chapters if start_chapter <= extract_num(f) <= end_chapter]

        if not selected:
            self._log(f"错误：未找到第{start_chapter}-{end_chapter}章的文件")
            return None

        # 合并内容
        merged = []
        for f in selected:
            content = self._read_file(f)
            merged.append(f"{'='*60}\n【{f.stem}】\n{'='*60}\n{content}\n")

        # 输出
        if output_name is None:
            output_name = f"合并_第{start_chapter}-{end_chapter}章.txt"

        output_path = self.dirs["blocks"] / output_name
        output_path.write_text("\n".join(merged), encoding='utf-8')
        self._log(f"已合并 {len(selected)} 章到 {output_path.name}")
        return output_path

    def get_scan_task(self, start_chapter, count=30):
        """生成 scan 任务描述（JSON格式），自动合并章节为单个文件"""
        target_files, start_num, end_num = self._get_chapter_files(start_chapter, count)

        if not target_files:
            return json.dumps({"error": "No chapters found starting from the specified chapter."}, ensure_ascii=False)

        prompt_template_path = self.dirs["config"] / "高光点扫描提示词.txt"
        if not prompt_template_path.exists():
            return json.dumps({"error": f"Template not found at {prompt_template_path}"}, ensure_ascii=False)

        # 自动合并章节
        merged_file = self.merge_chapters(start_num, end_num)
        if not merged_file:
            return json.dumps({"error": "Failed to merge chapters."}, ensure_ascii=False)

        task = {
            "task_type": "scan",
            "description": f"高光点扫描：第{start_num}-{end_num}章（共{len(target_files)}章）",
            "chapter_range": {
                "start": start_num,
                "end": end_num,
                "count": len(target_files)
            },
            "files": {
                "prompt_template": str(prompt_template_path),
                "merged_chapters": str(merged_file),
            },
            "output": {
                "file": str(self.dirs["blocks"] / f"高光点_第{start_num}-{end_num}章.json"),
                "format": "JSON"
            },
            "delegate_config": {
                "category": "novel-scan",
                "load_skills": ["novel-refiner"]
            }
        }
        return json.dumps(task, ensure_ascii=False, indent=2)

    def get_plan_task(self, start_chapter, count=50, highlights_file=None):
        """生成 plan 任务描述（JSON格式），自动合并章节为单个文件"""
        target_files, start_num, end_num = self._get_chapter_files(start_chapter, count)

        if not target_files:
            return json.dumps({"error": "No chapters found starting from the specified chapter."}, ensure_ascii=False)

        prompt_template_path = self.dirs["config"] / "剧情块提示词.txt"
        if not prompt_template_path.exists():
            return json.dumps({"error": f"Template not found at {prompt_template_path}"}, ensure_ascii=False)

        # Try to find highlights file
        hl_file_path = None
        if highlights_file:
            hl_path = Path(highlights_file)
            if hl_path.exists():
                hl_file_path = str(hl_path)
        else:
            # Auto-detect highlights file
            for hl_file in self.dirs["blocks"].glob("高光点_*.json"):
                try:
                    hl_content = self._read_file(hl_file)
                    hl_data = json.loads(hl_content)
                    scan_range = hl_data.get("scan_range", "")
                    if f"第{start_num}" in scan_range or f"-{end_num}" in scan_range:
                        hl_file_path = str(hl_file)
                        self._log(f"Found matching highlights file: {hl_file.name}")
                        break
                except (json.JSONDecodeError, Exception):
                    continue

        # 检查是否已有合并文件
        merged_filename = f"合并_第{start_num}-{end_num}章.txt"
        merged_file = self.dirs["blocks"] / merged_filename
        if not merged_file.exists():
            merged_file = self.merge_chapters(start_num, end_num)
            if not merged_file:
                return json.dumps({"error": "Failed to merge chapters."}, ensure_ascii=False)
        else:
            self._log(f"使用已有合并文件: {merged_filename}")

        task = {
            "task_type": "plan",
            "description": f"剧情块规划：第{start_num}-{end_num}章（共{len(target_files)}章）",
            "chapter_range": {
                "start": start_num,
                "end": end_num,
                "count": len(target_files)
            },
            "files": {
                "prompt_template": str(prompt_template_path),
                "merged_chapters": str(merged_file),
                "highlights_file": hl_file_path
            },
            "output": {
                "file": str(self.dirs["blocks"] / f"规划_第{start_num}-{end_num}章.json"),
                "format": "JSON"
            },
            "delegate_config": {
                "category": "novel-scan",
                "load_skills": ["novel-refiner"]
            }
        }
        return json.dumps(task, ensure_ascii=False, indent=2)

    def get_refine_task(self, block_file_path):
        """生成 refine 任务描述（JSON格式），自动合并章节为单个文件"""
        block_path = Path(block_file_path)
        if not block_path.exists():
            return json.dumps({"error": f"Block file {block_file_path} not found."}, ensure_ascii=False)

        match = re.search(r"第(\d+)-(\d+)章", block_path.name)
        if not match:
            return json.dumps({"error": "Could not parse chapter range from filename."}, ensure_ascii=False)

        start_chap, end_chap = int(match.group(1)), int(match.group(2))

        if not self.context_file.exists():
            return json.dumps({"error": f"story_context.txt not found at {self.context_file}"}, ensure_ascii=False)

        refine_template_path = self.dirs["config"] / "小说精炼提示词.txt"
        if not refine_template_path.exists():
            return json.dumps({"error": f"Template not found at {refine_template_path}"}, ensure_ascii=False)

        # 检查是否已有合并文件
        merged_filename = f"合并_第{start_chap}-{end_chap}章.txt"
        merged_file = self.dirs["blocks"] / merged_filename
        if not merged_file.exists():
            merged_file = self.merge_chapters(start_chap, end_chap)
            if not merged_file:
                return json.dumps({"error": "Failed to merge chapters."}, ensure_ascii=False)
        else:
            self._log(f"使用已有合并文件: {merged_filename}")

        # 计算章节数
        all_chapters = []
        for f in self.dirs["source"].rglob("*.txt"):
            if re.match(r"第\d+-", f.name):
                all_chapters.append(f)

        def extract_num(path):
            m = re.search(r"第(\d+)-", path.name)
            return int(m.group(1)) if m else 999999

        chapter_count = len([f for f in all_chapters if start_chap <= extract_num(f) <= end_chap])

        task = {
            "task_type": "refine",
            "description": f"文案精炼：第{start_chap}-{end_chap}章（共{chapter_count}章）",
            "chapter_range": {
                "start": start_chap,
                "end": end_chap,
                "count": chapter_count
            },
            "files": {
                "prompt_template": str(refine_template_path),
                "block_file": str(block_path),
                "context_file": str(self.context_file),
                "merged_chapters": str(merged_file),
            },
            "output": {
                "dir": str(self.dirs["output"]),
                "format": "TXT"
            },
            "delegate_config": {
                "category": "novel-writing",
                "load_skills": ["novel-refiner"]
            }
        }
        return json.dumps(task, ensure_ascii=False, indent=2)

    def execute_refine_with_gemini(self, block_file_path, block_id=None):
        """使用 Gemini CLI 直接执行 refine 任务"""
        block_path = Path(block_file_path)
        if not block_path.exists():
            self._log(f"错误：找不到文件 {block_file_path}")
            return False
        
        # 读取剧情块规划 JSON
        block_json_content = self._read_file(block_path)
        try:
            blocks = json.loads(block_json_content)
        except json.JSONDecodeError as e:
            self._log(f"错误：JSON 解析失败 - {e}")
            return False
        
        # 如果指定了 block_id，找到对应的块并只处理它
        target_block = None
        if block_id:
            for b in blocks:
                if b.get("block_id") == block_id:
                    target_block = b
                    break
            if not target_block:
                self._log(f"错误：找不到块 {block_id}")
                return False
            # 只保留目标块
            blocks = [target_block]
        else:
            # 没指定 block_id，处理第一个块
            target_block = blocks[0]
            blocks = [target_block]
        
        # 从块的 range 字段解析章节范围
        range_str = target_block.get("range", "")
        range_match = re.search(r"第(\d+)-(\d+)章", range_str)
        if not range_match:
            self._log(f"错误：无法从 range '{range_str}' 解析章节范围")
            return False
        
        start_chap, end_chap = int(range_match.group(1)), int(range_match.group(2))
        self._log(f"处理块 {target_block['block_id']}：第{start_chap}-{end_chap}章")
        
        # 合并该块对应的章节
        merged_filename = f"合并_第{start_chap}-{end_chap}章.txt"
        merged_file = self.dirs["blocks"] / merged_filename
        if not merged_file.exists():
            merged_file = self.merge_chapters(start_chap, end_chap)
            if not merged_file:
                self._log("错误：合并章节失败")
                return False
        else:
            self._log(f"使用已有合并文件: {merged_filename}")
        
        # 读取提示词模板
        refine_template_path = self.dirs["config"] / "小说精炼提示词.txt"
        if not refine_template_path.exists():
            self._log(f"错误：找不到提示词模板 {refine_template_path}")
            return False
        prompt_template = self._read_file(refine_template_path)
        
        # 读取剧情状态表
        if not self.context_file.exists():
            self._log(f"错误：找不到 story_context.txt")
            return False
        context_content = self._read_file(self.context_file)
        
        # 读取合并后的章节原文
        merged_content = self._read_file(merged_file)
        
        # 只输出当前块的规划
        block_content = json.dumps(blocks, ensure_ascii=False, indent=2)
        
        # 确定当前处理的块
        current_block_hint = f"\n\n**当前处理的块**：{target_block['block_id']}（只处理这一个块）"
        
        # 构建完整提示词
        full_prompt = f"""{prompt_template}

---

# 剧情状态表

{context_content}

---

# 剧情块规划

{block_content}
{current_block_hint}

---

# 待精炼原文

{merged_content}

---

# 输出要求

请将精炼后的文案保存到：{self.dirs['output']}/精炼_{target_block['block_id']}_第{start_chap}-{end_chap}章.txt
"""
        
        self._log(f"正在调用 Gemini CLI 执行精炼任务...")
        self._log(f"章节范围：第{start_chap}-{end_chap}章")
        
        # 将 prompt 写入临时文件，避免命令行参数长度限制和特殊字符问题
        import tempfile
        prompt_file = Path(tempfile.gettempdir()) / "gemini_refine_prompt.txt"
        prompt_file.write_text(full_prompt, encoding='utf-8')
        self._log(f"Prompt 已写入临时文件：{prompt_file}")
        
        # 调用 Gemini CLI
        # Windows 上需要用 shell=True 才能找到 npm 安装的全局命令
        try:
            # 使用 stdin 传入 prompt，避免命令行长度限制
            with open(prompt_file, 'r', encoding='utf-8') as f:
                result = subprocess.run(
                    "gemini --yolo",  # shell=True 时用字符串
                    stdin=f,
                    capture_output=True,
                    text=True,
                    timeout=600,  # 10分钟超时
                    encoding='utf-8',
                    shell=True  # Windows 需要 shell=True 才能找到 npm 全局命令
                )
            
            if result.returncode == 0:
                self._log("Gemini CLI 执行完成")
                print(result.stdout)
                return True
            else:
                self._log(f"Gemini CLI 执行失败：{result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            self._log("Gemini CLI 执行超时（10分钟）")
            return False
        except FileNotFoundError:
            self._log("错误：找不到 gemini 命令，请确保 Gemini CLI 已安装并在 PATH 中")
            return False
        except Exception as e:
            self._log(f"执行出错：{e}")
            return False


def main():
    parser = argparse.ArgumentParser(description="Novel Refiner Tool")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("init", help="Initialize project and split files")

    scan_parser = subparsers.add_parser("scan", help="Generate scan task (JSON)")
    scan_parser.add_argument("start", type=int, help="Start chapter number")
    scan_parser.add_argument("count", type=int, nargs='?', default=30, help="Max chapters (default: 30)")

    plan_parser = subparsers.add_parser("plan", help="Generate plan task (JSON)")
    plan_parser.add_argument("start", type=int, help="Start chapter number")
    plan_parser.add_argument("count", type=int, nargs='?', default=50, help="Max chapters (default: 50)")
    plan_parser.add_argument("--highlights", type=str, help="Path to highlights JSON file")

    refine_parser = subparsers.add_parser("refine", help="Generate refine task (JSON)")
    refine_parser.add_argument("block_file", type=str, help="Path to the plot block file")

    refine_exec_parser = subparsers.add_parser("refine-exec", help="Execute refine with Gemini CLI")
    refine_exec_parser.add_argument("block_file", type=str, help="Path to the plot block file")
    refine_exec_parser.add_argument("--block", type=str, help="Specific block ID to process (e.g., B1)")

    args = parser.parse_args()
    refiner = NovelRefiner()

    if args.command == "init":
        refiner.init_project()
    elif args.command == "scan":
        print(refiner.get_scan_task(args.start, args.count))
    elif args.command == "plan":
        highlights = getattr(args, 'highlights', None)
        print(refiner.get_plan_task(args.start, args.count, highlights))
    elif args.command == "refine":
        print(refiner.get_refine_task(args.block_file))
    elif args.command == "refine-exec":
        block_id = getattr(args, 'block', None)
        success = refiner.execute_refine_with_gemini(args.block_file, block_id)
        if not success:
            exit(1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
