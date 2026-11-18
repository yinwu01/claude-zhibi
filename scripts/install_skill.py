"""Build and install the complete Skill to an explicitly chosen directory."""
import argparse
import os
import sys
import tempfile
import zipfile
from pathlib import Path

from build_skill import build

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from zhibi.models import InputError


def host_destination(host):
    folder = ".agents" if host == "codex" else ".other-agent"
    return Path.home() / folder / "skills" / "zhibi"


def install(destination, replace=False):
    destination = Path(destination).expanduser().absolute()
    # Use the same canonical parent for fresh installs and upgrades, including
    # macOS paths under /var. Keep checking the Skill directory itself separately.
    destination = destination.parent.resolve() / destination.name
    if destination.is_symlink() or (destination.exists() and not replace):
        raise ValueError("目标已存在。请先保留旧版本，再选择新的目录；不会覆盖已有 Skill。")
    if replace and destination.exists() and not all(
        (destination / file).is_file() for file in ("SKILL.md", "scripts/zhibi.py", "assets/zhibi-core.pyz")
    ):
        raise ValueError("目标不是完整的已安装知彼 Skill。")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".zhibi-install-", dir=destination.parent) as tmp:
        temporary = Path(tmp)
        result = build(temporary / "build")
        if replace:
            from zhibi.delivery import install as install_archive
            status = install_archive(result["skill"], result["sha256"], destination, replace=True)
            return destination, status["previous_version"]
        with zipfile.ZipFile(result["skill"]) as archive:
            # This archive was built from the allowlisted repository files immediately above.
            archive.extractall(temporary / "unpacked")
        source = temporary / "unpacked" / "zhibi"
        if not (source / "scripts" / "zhibi.py").is_file() or not (source / "assets" / "zhibi-core.pyz").is_file():
            raise ValueError("Skill 构建不完整，未安装。")
        if destination.exists() or destination.is_symlink():
            raise ValueError("目标已被创建，未覆盖。")
        os.rename(source, destination)
    return destination, None


def main():
    parser = argparse.ArgumentParser(description="将知彼 Skill 与内置核心一起安装；无 pip，无网络。")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--host", choices=("codex",))
    group.add_argument("--dest", help="明确的 Skill 文件夹路径，例如 /path/to/skills/zhibi")
    parser.add_argument("--replace", action="store_true", help="升级已有知彼 Skill，并保留可恢复的旧版")
    args = parser.parse_args()
    if args.dest:
        destination = args.dest
    else:
        destination = host_destination(args.host)
    try:
        installed, previous = install(destination, args.replace)
    except (OSError, ValueError, InputError):
        parser.exit(2, "安装未完成：目标已存在、权限不足或构建不完整。未覆盖已有 Skill。\n")
    print("已安装完整知彼 Skill：" + str(installed))
    if previous:
        print("已保留旧版：" + previous)
        from shlex import join
        print("回退命令：" + join([sys.executable, str(installed / "scripts" / "zhibi.py"),
                                  "skill-rollback", "--dest", str(installed), "--previous", previous]))
    invocation = "$zhibi" if args.host == "codex" else "知彼（在宿主中按 Skill 名调用）"
    print("在宿主中选择知彼 Skill，或新开会话后输入：" + invocation + " 带我开始，从我当前做到的地方继续。")
    print("直接验证安装：python3 \"" + str(installed / "scripts" / "zhibi.py") + "\" doctor")


if __name__ == "__main__":
    main()
