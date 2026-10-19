# tools/ — 离线评测与数据集工具

这些脚本不属于在线服务，用于离线评测转写质量、抓取公开数据集做回归测试。
它们依赖上级目录的核心模块（engine/config），请**在 `backend/` 目录下以模块方式运行**：

```bash
cd backend
python -m tools.transcribe_cli  --help
python -m tools.diarize_cli     --help
```

## 脚本一览

| 脚本 | 用途 |
|---|---|
| `transcribe_cli.py` | 命令行转写单个音频文件，输出 JSON/文本 |
| `diarize_cli.py` | 命令行说话人分离（输出带说话人标签的时间轴） |
| `show_result.py` | 查看 data/results 下转写结果 JSON 的摘要 |
| `probe_audio.py` | 探测音频文件元信息（采样率/声道/时长/编码） |
| `cer_eval.py` | CER（字错误率）评测：转写结果 vs 人工标注 |
| `cer_long.py` | 长音频批量 CER 评测 |
| `fetch_ami.py` / `fetch_ms.py` / `extract_aishell4.py` | 下载/整理公开会议数据集（AMI、AISHELL-4 等） |
| `ab_compare.py` | 两个转写配置的 A/B 对比 |
| `test_fr11.py` / `test_fr28.py` | 功能回归用例 |

测试音频存放根目录可用环境变量 `MS_TEST_AUDIO` 配置（默认 `./test-audio/`，已加入 .gitignore）。
