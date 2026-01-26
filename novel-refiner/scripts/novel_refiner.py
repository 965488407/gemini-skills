import os
import re
import json
import shutil
import argparse
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
            self.root / ".gemini" / "skills" / "novel-refiner",
            Path.home() / ".gemini" / "skills" / "novel-refiner",
            Path(__file__).parent.parent,  # 相对于脚本位置
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
            re.compile(r"(?:^|\n|\s)(第[零一二三四五六七八九十百千万]+章[^\n]*)"),
            re.compile(r"(?:^|\n|\s)(第\d+章[^\n]*)"),
            re.compile(r"(?:^|\n|\s)((?:第[零一二三四五六七八九十百千万]+|第\d+)[章节卷集部][^\n]*)"),
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

    def get_planning_prompt(self, start_chapter, count=50):
        """Generates the prompt for Phase 1: Planning."""
        all_chapters = []
        for f in self.dirs["source"].rglob("*.txt"):
            if re.match(r"第\d+-", f.name):
                all_chapters.append(f)
                
        def extract_num(path):
            m = re.search(r"第(\d+)-", path.name)
            return int(m.group(1)) if m else 999999

        all_chapters.sort(key=extract_num)
        
        target_files = []
        total_chars = 0
        MAX_CHARS = 100000
        
        potential_files = [f for f in all_chapters if extract_num(f) >= start_chapter]
        end_chapter_num = start_chapter
        
        for f in potential_files:
            if len(target_files) >= count:
                break
            
            try:
                text = f.read_text(encoding="utf-8")
            except:
                continue
                
            if total_chars + len(text) > MAX_CHARS and len(target_files) > 0:
                break
                
            target_files.append(f)
            total_chars += len(text)
            end_chapter_num = extract_num(f)
        
        if not target_files:
            return "Error: No chapters found starting from the specified chapter."
            
        combined_content = ""
        for f in target_files:
            combined_content += f.read_text(encoding="utf-8") + "\n\n"
        
        prompt_template_path = self.dirs["config"] / "剧情块提示词.txt"
        if not prompt_template_path.exists():
            return f"Error: Template not found at {prompt_template_path}"
            
        prompt_template = self._read_file(prompt_template_path)
        final_prompt = (
            f"{prompt_template}\n\n"
            f"=== 预读内容 (第{start_chapter} - {end_chapter_num}章 | 共{len(target_files)}章) ===\n"
            f"{combined_content}"
        )
        return final_prompt

    def get_refining_prompt(self, block_file_path):
        """Generates the prompt for Phase 2: Refining."""
        block_path = Path(block_file_path)
        if not block_path.exists():
            return f"Error: Block file {block_file_path} not found."
            
        block_content = self._read_file(block_path)
        match = re.search(r"第(\d+)-(\d+)章", block_path.name)
        if not match:
            return "Error: Could not parse chapter range from filename."
            
        start_chap, end_chap = int(match.group(1)), int(match.group(2))
        
        if not self.context_file.exists():
            return f"Error: story_context.txt not found at {self.context_file}"
        context_content = self._read_file(self.context_file)
        
        all_chapters = []
        for f in self.dirs["source"].rglob("*.txt"):
            if re.match(r"第\d+-", f.name):
                all_chapters.append(f)
        
        def extract_num(path):
            m = re.search(r"第(\d+)-", path.name)
            return int(m.group(1)) if m else 999999
            
        target_chapters = [f for f in all_chapters if start_chap <= extract_num(f) <= end_chap]
        target_chapters.sort(key=extract_num)
        
        chapter_text = "\n".join([f.read_text(encoding="utf-8") for f in target_chapters])
        
        refine_template_path = self.dirs["config"] / "小说精炼提示词.txt"
        if not refine_template_path.exists():
            return f"Error: Template not found at {refine_template_path}"
        refine_template = self._read_file(refine_template_path)
        
        final_prompt = (
            f"{refine_template}\n\n"
            f"=== 1. 【剧情状态表】 (story_context.txt) ===\n{context_content}\n\n"
            f"=== 2. 【剧情块规划】 ===\n{block_content}\n\n"
            f"=== 3. 【待精炼原文】 (第{start_chap}-{end_chap}章) ===\n{chapter_text}"
        )
        return final_prompt


def main():
    parser = argparse.ArgumentParser(description="Novel Refiner Tool")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("init", help="Initialize project and split files")

    plan_parser = subparsers.add_parser("plan", help="Generate planning prompt")
    plan_parser.add_argument("start", type=int, help="Start chapter number")
    plan_parser.add_argument("count", type=int, nargs='?', default=50, help="Max chapters (default: 50)")

    refine_parser = subparsers.add_parser("refine", help="Generate refining prompt")
    refine_parser.add_argument("block_file", type=str, help="Path to the plot block file")

    args = parser.parse_args()
    refiner = NovelRefiner()
    
    if args.command == "init":
        refiner.init_project()
    elif args.command == "plan":
        print(refiner.get_planning_prompt(args.start, args.count))
    elif args.command == "refine":
        print(refiner.get_refining_prompt(args.block_file))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
