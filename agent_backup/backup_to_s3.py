"""
backup_to_s3.py — 将指定目录备份到 S3，每个目录每天一个版本，最多保留 N 个历史版本。

用法:
    python backup_to_s3.py -b <bucket> /path/dir1 /path/dir2
    python backup_to_s3.py -b <bucket> -k 5 -p backups /etc /var/www

依赖:
    pip install boto3
"""

import argparse
import datetime
import logging
import os
import sys
import tarfile
import tempfile
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

# ---------- 日志配置 ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def load_env_file(env_file: str) -> None:
    """从 .env 文件加载环境变量，已存在的环境变量不会被覆盖。"""
    path = Path(env_file)
    if not path.is_file():
        log.error("env 文件不存在: %s", env_file)
        sys.exit(1)
    with open(path) as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            # 跳过空行和注释
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                log.warning(".env 第 %d 行格式无效，已跳过: %s", lineno, line)
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            # 去除值两端的引号（支持单引号和双引号）
            value = value.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = value
    log.info("已加载 env 文件: %s", env_file)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="将本地目录备份到 S3，每天一个版本，自动轮转旧版本。"
    )
    parser.add_argument(
        "dirs",
        nargs="+",
        metavar="DIR",
        help="需要备份的目录（可指定多个）",
    )
    parser.add_argument(
        "-e",
        "--env-file",
        metavar="FILE",
        help="从指定的 .env 文件加载环境变量（优先于系统环境变量中未设置的值）",
    )
    parser.add_argument(
        "-b",
        "--bucket",
        default=None,
        help="S3 存储桶名称（也可通过 BACKUP_S3_BUCKET 环境变量设置）",
    )
    parser.add_argument(
        "-p",
        "--prefix",
        default="backups",
        help="S3 key 前缀（默认: backups）",
    )
    parser.add_argument(
        "-k",
        "--keep",
        type=int,
        default=5,
        help="每个目录保留的最大历史版本数（默认: 5）",
    )
    parser.add_argument(
        "-r",
        "--region",
        default=os.environ.get("AWS_DEFAULT_REGION", "us-east-1"),
        help="AWS 区域（默认: us-east-1）",
    )
    parser.add_argument(
        "--storage-class",
        default="STANDARD_IA",
        choices=["STANDARD", "STANDARD_IA", "ONEZONE_IA", "GLACIER", "DEEP_ARCHIVE"],
        help="S3 存储类型（默认: STANDARD_IA）",
    )
    parser.add_argument(
        "-n",
        "--dry-run",
        action="store_true",
        help="试运行：显示操作但不实际上传或删除",
    )
    return parser.parse_args()


def dir_to_key_prefix(src_dir: str) -> str:
    """将目录路径转换为 S3 安全的 key 片段，例如 /var/www/html → var_www_html"""
    return str(Path(src_dir).resolve()).lstrip("/").replace("/", "_")


def compress_directory(src_dir: str, dest_path: str) -> None:
    """将 src_dir 压缩为 tar.gz 文件到 dest_path。"""
    src = Path(src_dir).resolve()
    with tarfile.open(dest_path, "w:gz") as tar:
        tar.add(src, arcname=src.name)
    size_mb = os.path.getsize(dest_path) / 1024 / 1024
    log.info("压缩完成: %.2f MB  →  %s", size_mb, dest_path)


def list_existing_backups(
    s3: "boto3.client", bucket: str, s3_dir_prefix: str
) -> list[str]:
    """列出某目录在 S3 上已有的备份文件 key，按名称升序（最旧在前）。"""
    keys = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=s3_dir_prefix + "/"):
        for obj in page.get("Contents", []):
            keys.append(obj["Key"])
    keys.sort()
    return keys


def already_backed_up_today(keys: list[str], date_tag: str) -> bool:
    """判断今天是否已经存在备份。"""
    return any(date_tag in k for k in keys)


def rotate_old_versions(
    s3: "boto3.client",
    bucket: str,
    keys: list[str],
    max_versions: int,
    dry_run: bool,
) -> None:
    """删除超出 max_versions 的最旧备份。"""
    excess = len(keys) - max_versions
    if excess <= 0:
        log.info("当前版本数: %d / %d，无需清理", len(keys), max_versions)
        return
    to_delete = keys[:excess]
    for key in to_delete:
        if dry_run:
            log.info("[试运行] 删除旧版本: s3://%s/%s", bucket, key)
        else:
            s3.delete_object(Bucket=bucket, Key=key)
            log.info("已删除旧版本: s3://%s/%s", bucket, key)


def backup_directory(
    s3: "boto3.client",
    src_dir: str,
    bucket: str,
    prefix: str,
    max_versions: int,
    storage_class: str,
    dry_run: bool,
) -> bool:
    """备份单个目录，返回是否成功。"""
    src_path = Path(src_dir)
    if not src_path.is_dir():
        log.warning("目录不存在，跳过: %s", src_dir)
        return True

    today = datetime.date.today().strftime("%Y-%m-%d")
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    dir_key = dir_to_key_prefix(src_dir)
    s3_dir_prefix = f"{prefix}/{dir_key}"
    archive_name = f"{dir_key}_{timestamp}.tar.gz"
    s3_key = f"{s3_dir_prefix}/{archive_name}"

    log.info("── 备份目录: %s", src_dir)

    # 检查今天是否已备份
    existing_keys = list_existing_backups(s3, bucket, s3_dir_prefix)
    if already_backed_up_today(existing_keys, today):
        log.warning("今天 (%s) 已存在备份，跳过: %s", today, src_dir)
        return True

    with tempfile.TemporaryDirectory() as tmpdir:
        archive_path = os.path.join(tmpdir, archive_name)

        # 压缩
        try:
            if dry_run:
                log.info("[试运行] 压缩 %s  →  %s", src_dir, archive_path)
            else:
                log.info("正在压缩: %s", src_dir)
                compress_directory(src_dir, archive_path)
        except Exception as e:
            log.error("压缩失败 (%s): %s", src_dir, e)
            return False

        # 上传
        try:
            if dry_run:
                log.info("[试运行] 上传  s3://%s/%s", bucket, s3_key)
            else:
                log.info("正在上传: s3://%s/%s", bucket, s3_key)
                s3.upload_file(
                    archive_path,
                    bucket,
                    s3_key,
                    ExtraArgs={"StorageClass": storage_class},
                )
                log.info("上传成功: s3://%s/%s", bucket, s3_key)
        except (BotoCoreError, ClientError) as e:
            log.error("上传失败 (%s): %s", src_dir, e)
            return False

    # 轮转旧版本（上传成功后刷新列表）
    if not dry_run:
        existing_keys = list_existing_backups(s3, bucket, s3_dir_prefix)
    else:
        existing_keys = existing_keys + [s3_key]  # 模拟新增

    rotate_old_versions(s3, bucket, existing_keys, max_versions, dry_run)
    return True


def main() -> None:
    args = parse_args()

    # 最先加载 env 文件，后续参数解析才能读到其中的环境变量
    if args.env_file:
        load_env_file(args.env_file)

    # env 文件加载后再确定 bucket / region（命令行显式传入优先）
    if args.bucket is None:
        args.bucket = os.environ.get("BACKUP_S3_BUCKET")
    if not args.bucket:
        log.error("必须通过 -b/--bucket 或环境变量 BACKUP_S3_BUCKET 指定 S3 存储桶")
        sys.exit(1)

    if args.region == "us-east-1":  # 若仍是默认值，尝试从环境变量更新
        args.region = os.environ.get("AWS_DEFAULT_REGION", args.region)

    if args.dry_run:
        log.warning("试运行模式：不会实际上传或删除任何文件")

    try:
        s3 = boto3.client(
            "s3",
            region_name=args.region,
            config=Config(
                signature_version="s3",
                s3={
                    "addressing_style": os.environ.get(
                        "AWS_ADDRESSING_STYLE", "virtual"
                    )
                },
            ),
        )
        # 快速验证 bucket 是否可访问
        s3.head_bucket(Bucket=args.bucket)
    except ClientError as e:
        log.error("无法访问 S3 存储桶 '%s': %s", args.bucket, e)
        sys.exit(1)

    log.info("===== S3 备份开始 =====")
    log.info("存储桶: s3://%s/%s | 最大版本数: %d", args.bucket, args.prefix, args.keep)

    failed = []
    for d in args.dirs:
        ok = backup_directory(
            s3=s3,
            src_dir=d,
            bucket=args.bucket,
            prefix=args.prefix,
            max_versions=args.keep,
            storage_class=args.storage_class,
            dry_run=args.dry_run,
        )
        if not ok:
            failed.append(d)

    log.info("===== 备份完成 =====")
    if failed:
        log.error("以下目录备份失败: %s", ", ".join(failed))
        sys.exit(1)


if __name__ == "__main__":
    main()
