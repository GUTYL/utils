# utills

通用工具仓库，包含备份脚本与示例入口程序。

## 目录结构

- `main.py`: 示例入口，打印 `Hello from utils!`
- `agent_backup/backup_to_s3.py`: 将本地目录备份到 AWS S3 的脚本（支持定时、轮转、dry-run等）。
- `agent_backup/README.md`: 备份脚本使用说明（详见此文件）。
- `pyproject.toml`: 项目元信息与依赖配置。

## 运行环境

本项目基于 Python 3.14+。

- 项目依赖使用 `uv` 管理（例如 `uv sync`、`uv run` 等）。

## 快速开始

0. 使用 `uv` 初始化项目（示例）:

```bash
# 同步依赖
uv sync

# 运行 main
uv run main.py

# 代码检查
ruff check .

# 代码格式化
ruff format .
```

1. 运行备份脚本（推荐先阅读 `agent_backup/README.md`）:

```bash
uv run agent_backup/backup_to_s3.py -h
```

2. JSONL 转 Excel: 数组/嵌套字典

```bash
uv run jsonl_to_excel.py input.jsonl output.xlsx
```

依赖:

```bash
pip install pandas openpyxl
```


## 备份脚本概览（agent_backup/backup_to_s3.py）

- 支持多目录备份
- 每日一次（避免重复备份）
- 历史保留数量控制（默认 5 份）
- tar.gz 压缩并上传 S3
- 试运行 `-n` 模式
- `.env` / 环境变量 / 命令行参数灵活配置

## 贡献

欢迎提交 issue/PR，描述你希望新增的工具或改进点。

## 许可证

本项目采用 `MIT` 许可证（如 `LICENSE` 所示）。
