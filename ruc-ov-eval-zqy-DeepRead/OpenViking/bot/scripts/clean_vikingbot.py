#!/usr/bin/env python3
"""
VikingBot一键清理脚本

清理以下内容：
- sessions/ - 会话文件
- workspace/ - 工作空间文件
- cron/ - 定时任务数据
- 保留 config.json 配置文件

使用方法：
    python clean_vikingbot.py              # 交互式确认
    python clean_vikingbot.py --yes        # 不确认直接删除
    python clean_vikingbot.py --dry-run    # 预览删除内容，不实际删除
"""

import sys
import shutil
from pathlib import Path


def is_dry_run() -> bool:
    """检查是否是预览模式"""
    return "--dry-run" in sys.argv


def get_vikingbot_dir() -> Path:
    """获取vikingbot数据目录"""
    return Path.home() / ".vikingbot"


def confirm_action(message: str) -> bool:
    """交互式确认"""
    if "--yes" in sys.argv or "-y" in sys.argv:
        return True

    try:
        response = input(f"\n{message} (y/N): ").strip().lower()
        return response in ["y", "yes"]
    except (EOFError, KeyboardInterrupt):
        print("\n\n⏭️   跳过操作")
        return False


def clean_directory(dir_path: Path, description: str) -> bool:
    """清理指定目录"""
    if not dir_path.exists():
        print(f"  ℹ️  {description} 不存在，跳过")
        return True

    if not confirm_action(f"确定要删除 {description} 吗？"):
        print(f"  ⏭️   跳过删除 {description}")
        return False

    if is_dry_run():
        print(f"  [预览] 将删除 {description}")
        return True

    try:
        shutil.rmtree(dir_path)
        print(f"  ✅ 已删除 {description}")
        return True
    except Exception as e:
        print(f"  ❌ 删除 {description} 失败: {e}")
        return False


def delete_file(file_path: Path, description: str) -> bool:
    """删除指定文件"""
    if not file_path.exists():
        return True

    if is_dry_run():
        print(f"  [预览] 将删除 {description}")
        return True

    try:
        file_path.unlink()
        print(f"  ✅ 已删除 {description}")
        return True
    except Exception as e:
        print(f"  ❌ 删除 {description} 失败: {e}")
        return False


def main():
    """主函数"""
    print("=" * 60)
    print("🧹 VikingBot 一键清理工具")
    print("=" * 60)

    if is_dry_run():
        print("\n[预览模式] 不会实际删除任何文件")

    vikingbot_dir = get_vikingbot_dir()

    if not vikingbot_dir.exists():
        print(f"\n⚠️  VikingBot目录不存在: {vikingbot_dir}")
        print("   没有需要清理的内容")
        return 0

    print(f"\n📂 VikingBot目录: {vikingbot_dir}")
    print("\n将清理以下内容：")
    print("  1. sessions/ - 会话文件")
    print("  2. workspace/ - 工作空间文件")
    print("  3. cron/ - 定时任务数据")
    print("  4. sandboxes/ - 沙箱数据")
    print("  5. bridge/ - Bridge数据")
    print("\n⚠️  注意: config.json 配置文件将保留")

    # 统计清理前的文件
    total_deleted = 0
    items_to_clean = [
        ("sessions", "sessions/ 会话目录"),
        ("workspace", "workspace/ 工作空间"),
        ("cron", "cron/ 定时任务数据"),
        ("sandboxes", "sandboxes/ 沙箱目录"),
        ("bridge", "bridge/ Bridge目录"),
    ]

    print("\n" + "-" * 60)
    for dir_name, description in items_to_clean:
        dir_path = vikingbot_dir / dir_name
        if clean_directory(dir_path, description):
            total_deleted += 1

    # 检查是否还有其他临时文件（配置备份文件默认不删除）
    print("\n" + "-" * 60)
    print("检查临时文件...")

    # 只显示配置备份文件，但不删除
    backup_files = list(vikingbot_dir.glob("config*.json"))
    backup_files = [f for f in backup_files if f.name != "config.json"]

    if backup_files:
        print(f"\n发现 {len(backup_files)} 个配置备份文件（不自动删除）:")
        for f in backup_files:
            print(f"  - {f.name}")
        print("\n💡 如需删除这些备份文件，请手动删除或修改脚本启用此功能")

    print("\n" + "=" * 60)
    if is_dry_run():
        print("📋 [预览模式] 以上是将要删除的内容预览")
    elif total_deleted > 0:
        print(f"✅ 清理完成！共删除了 {total_deleted} 个目录")
    else:
        print("ℹ️  没有需要清理的内容")
    print("\n💡 下次运行 vikingbot 时，workspace 会自动重新初始化")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
