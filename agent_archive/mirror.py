from __future__ import annotations
import os, shutil
from agent_archive.models import SessionRef


def mirror(ref: SessionRef, archive_root: str, prefer_hardlink: bool = True) -> str:
    """把源文件镜像进 raw/<source>/<basename>，返回相对 raw_ref。
    优先硬链接（同盘、append-only）；失败或不偏好则拷贝。重复调用幂等。"""
    rel = os.path.join("raw", ref.source, os.path.basename(ref.path))
    dest = os.path.join(archive_root, rel)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.exists(dest):
        os.remove(dest)
    if prefer_hardlink:
        try:
            os.link(ref.path, dest)
            return rel
        except OSError:
            pass  # 跨盘/不支持 → 回退拷贝
    shutil.copy2(ref.path, dest)
    return rel
