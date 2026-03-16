# backup_to_s3.py

将本地目录备份到 AWS S3，支持多目录、每天一个版本、自动轮转旧版本。

## 功能

- 支持同时备份多个目录
- 每个目录每天只备份一次（当天已有备份则自动跳过）
- 每个目录最多保留 N 个历史版本（默认 5 个），超出时自动删除最旧的
- 备份文件以 `tar.gz` 格式压缩后上传到 S3
- 支持试运行模式（`-n`），不实际上传或删除任何文件
- 支持通过 `.env` 文件统一管理配置

## 依赖

- Python 3.9+
- [boto3](https://boto3.amazonaws.com/v1/documentation/api/latest/index.html)

```bash
pip install boto3
```

## 配置

AWS 凭证和脚本参数可通过以下任一方式配置（优先级从高到低）：

**方式一：命令行参数**
```bash
python backup_to_s3.py -b my-bucket -r us-east-1 /etc /var/www
```

**方式二：`.env` 文件**（推荐用于定时任务）

创建 `.env` 文件：
```ini
# AWS 凭证
AWS_ACCESS_KEY_ID=your-access-key
AWS_SECRET_ACCESS_KEY=your-secret-key
AWS_DEFAULT_REGION=us-east-1

# 备份配置
BACKUP_S3_BUCKET=my-bucket
```

然后通过 `-e` 参数加载：
```bash
python backup_to_s3.py -e /etc/backup.env /etc /var/www
```

**方式三：系统环境变量**
```bash
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
export AWS_DEFAULT_REGION=us-east-1
export BACKUP_S3_BUCKET=my-bucket
```

> `.env` 文件中的变量不会覆盖系统中已设置的同名环境变量。

## 用法

```
python backup_to_s3.py [选项] <目录1> [目录2 ...]
```

### 选项

| 选项 | 说明 | 默认值 |
|------|------|--------|
| `-e`, `--env-file` | 从指定 `.env` 文件加载环境变量 | — |
| `-b`, `--bucket` | S3 存储桶名称（也可通过 `BACKUP_S3_BUCKET` 环境变量设置） | — |
| `-p`, `--prefix` | S3 key 前缀 | `backups` |
| `-k`, `--keep` | 每个目录保留的最大历史版本数 | `5` |
| `-r`, `--region` | AWS 区域（也可通过 `AWS_DEFAULT_REGION` 环境变量设置） | `us-east-1` |
| `--storage-class` | S3 存储类型，可选 `STANDARD` / `STANDARD_IA` / `ONEZONE_IA` / `GLACIER` / `DEEP_ARCHIVE` | `STANDARD_IA` |
| `-n`, `--dry-run` | 试运行，只打印操作，不实际执行 | — |

### 示例

```bash
# 通过 .env 文件配置，备份~/.openclaw、~/.nanobot目录
python backup_to_s3.py -e .env ~/.openclaw ~/.nanobot

# 命令行直接指定 bucket
python backup_to_s3.py -b my-bucket ~/.openclaw ~/.nanobot

# 自定义保留版本数
python backup_to_s3.py -e .env -k 3 /data

# 指定 S3 前缀和存储类型
python backup_to_s3.py -e .env -p server-backups --storage-class GLACIER /var/www

# 试运行，查看将执行哪些操作
python backup_to_s3.py -e .env -n /etc /var/www
```

## S3 存储结构

```
s3://my-bucket/
└── backups/
    ├── etc/
    │   ├── etc_20260312_020000.tar.gz
    │   ├── etc_20260313_020000.tar.gz
    │   └── etc_20260314_020000.tar.gz
    └── var_www/
        ├── var_www_20260312_020000.tar.gz
        └── var_www_20260314_020000.tar.gz
```

目录路径中的 `/` 会被替换为 `_` 作为 S3 key，例如 `/var/www` → `var_www`。

## 定时执行（cron）

每天凌晨 2 点自动备份：

```bash
crontab -e
```

添加以下行：

```
0 2 * * * /usr/bin/python3 /path/to/backup_to_s3.py -b my-bucket /etc /var/www >> /var/log/s3_backup.log 2>&1
```
