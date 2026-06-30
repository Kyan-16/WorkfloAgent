"""
三层记忆 — 对话持久化存储层

两层存储后端：
1. 文件存储（YYYY-MM-DD.md + MEMORY.md）
2. SQLite 存储（conversation_store）

数据流：
  每次对话结束 → summarizer 生成 Daily 总结 → storage 写入文件
  Deep Dream 触发 → 读取所有 Daily + MEMORY.md → LLM 蒸馏 → 写回 MEMORY.md
"""
import os
import json
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class MemoryStore:
    """
    记忆文件存储

    目录结构：
      {base_dir}/daily/YYYY-MM-DD.md   - 每日总结
      {base_dir}/MEMORY.md             - 核心记忆（Deep Dream 输出）
      {base_dir}/evolution.jsonl        - 进化审计日志
    """

    def __init__(self, base_dir: str = "data/memory"):
        self.base_dir = Path(base_dir)
        self.daily_dir = self.base_dir / "daily"
        self.memory_file = self.base_dir / "MEMORY.md"
        self.evolution_log = self.base_dir / "evolution.jsonl"

        self.daily_dir.mkdir(parents=True, exist_ok=True)

    # ── Daily 总结 ──

    def save_daily(self, summary: str, entry_date: Optional[date] = None) -> Path:
        """保存每日总结"""
        entry_date = entry_date or date.today()
        filepath = self.daily_dir / f"{entry_date.isoformat()}.md"

        with open(filepath, "a", encoding="utf-8") as f:
            f.write(f"\n\n## {datetime.now().strftime('%H:%M')}\n{summary.strip()}\n")

        logger.info(f"Daily 总结已保存: {filepath}")
        return filepath

    def load_daily(self, days: int = 7) -> list[dict]:
        """加载最近 N 天的每日总结"""
        entries = []
        files = sorted(self.daily_dir.glob("*.md"), reverse=True)[:days]

        for filepath in files:
            date_str = filepath.stem
            content = filepath.read_text(encoding="utf-8").strip()
            if content:
                entries.append({"date": date_str, "content": content})

        return entries

    def get_daily_file(self, entry_date: Optional[date] = None) -> Path:
        """获取指定日期的 daily 文件路径"""
        entry_date = entry_date or date.today()
        return self.daily_dir / f"{entry_date.isoformat()}.md"

    # ── MEMORY.md ──

    def load_memory(self) -> str:
        """加载核心记忆"""
        if self.memory_file.exists():
            return self.memory_file.read_text(encoding="utf-8").strip()
        return ""

    def save_memory(self, content: str):
        """保存核心记忆（先备份再覆盖）"""
        # 备份旧版本
        if self.memory_file.exists():
            backup_path = self.base_dir / f"MEMORY.md.bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            self.memory_file.rename(backup_path)
            logger.info(f"核心记忆已备份: {backup_path}")

        self.memory_file.write_text(content.strip(), encoding="utf-8")
        logger.info(f"核心记忆已更新: {self.memory_file}")

    # ── 进化审计日志 ──

    def log_evolution(self, entry: dict):
        """记录进化事件"""
        entry["timestamp"] = datetime.now().isoformat()
        with open(self.evolution_log, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def get_evolution_history(self, limit: int = 20) -> list[dict]:
        """获取进化历史"""
        if not self.evolution_log.exists():
            return []

        entries = []
        with open(self.evolution_log, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

        return entries[-limit:]

    # ── 快照 ──

    def create_snapshot(self) -> str:
        """创建当前记忆的快照"""
        snapshot_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        snapshot_dir = self.base_dir / "snapshots" / snapshot_id
        snapshot_dir.mkdir(parents=True, exist_ok=True)

        # 备份 MEMORY.md
        if self.memory_file.exists():
            import shutil
            shutil.copy2(self.memory_file, snapshot_dir / "MEMORY.md")

        # 备份今日 daily
        today_file = self.get_daily_file()
        if today_file.exists():
            import shutil
            shutil.copy2(today_file, snapshot_dir / f"{date.today().isoformat()}.md")

        return snapshot_id

    def rollback(self, snapshot_id: str):
        """回滚到指定快照"""
        snapshot_dir = self.base_dir / "snapshots" / snapshot_id
        if not snapshot_dir.exists():
            raise FileNotFoundError(f"快照不存在: {snapshot_id}")

        import shutil

        snapshot_memory = snapshot_dir / "MEMORY.md"
        if snapshot_memory.exists():
            shutil.copy2(snapshot_memory, self.memory_file)
            logger.info(f"已回滚 MEMORY.md 到快照 {snapshot_id}")

    def delete_snapshot(self, snapshot_id: str):
        """删除快照"""
        snapshot_dir = self.base_dir / "snapshots" / snapshot_id
        if snapshot_dir.exists():
            import shutil
            shutil.rmtree(snapshot_dir)


# ── 全局单例 ──

_default_store: Optional[MemoryStore] = None


def get_memory_store(base_dir: str = "data/memory") -> MemoryStore:
    """获取全局记忆存储实例"""
    global _default_store
    if _default_store is None:
        _default_store = MemoryStore(base_dir)
    return _default_store
