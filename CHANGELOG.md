# Changelog / 更新日志

All notable changes to MeetScribe. 中文为主，每个版本首行附英文摘要。
格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 SemVer。

## [Unreleased]

### Changed

- **产品定位：仅桌面端（PC 浏览器）。** 移动端停止专项投入；现有响应式样式保留但不再维护。
  / Desktop-only product: mobile is not officially supported (responsive styles kept, unmaintained).

## [1.4.0] - 2026-10-26

> Desktop polish & release hardening / 桌面端体验收口、可复现性加固与正式发版。

### Added

- 检索召回回归集：15 条会议语料 × 15 条查询的端到端断言（recall@5 ≥ 0.95、MRR ≥ 0.85），
  防止分词/融合参数改动导致召回悄悄劣化；另含"语料外专名零误召回"用例。
- 导出可读化：文件名由录音 id 改为「会议名_YYYYMMDD」；`Content-Disposition` 支持
  RFC5987 中文名（含 ASCII 兜底）；Word 导出写入标题/作者/备注属性；Markdown 头部
  增加录音名/日期/时长/说话人数来源行。
- 前端构建版本可见：关于弹层显示 `web <git sha> · 构建时间`；旧 chunk 加载失败时自动
  硬刷新一次，避免浏览器停留在旧 bundle。
- 声纹录入防呆：勾选「存为声纹」但未改名时给出内联提示并禁用保存，不再静默失败。
- 备份与迁移：新增 `scripts/backup.sh`（tar.gz，装有 sqlite3 时额外输出一致性数据库
  快照）与 `scripts/backup.ps1`（zip），保留最近 N 份；README 中英新增「备份与迁移」章节。
- 依赖安全扫描：CI 新增 `deps-audit` job——pip-audit `--strict`（阻断）；npm audit
  `--audit-level=high` 暂为报告模式（已知 react-router <7.18 高危，待 v7 迁移后恢复阻断）。
  随批升级：pytest 8→9、CI 内升级 pip/setuptools、filelock ≥4.2.1（Python≥3.11）。

### Fixed

- 修复 CI 自 1.2.0-c 起持续失败：测试环境缺少 flask/numpy/requests 等依赖（requirements-dev
  仅含 pytest），并修正其注释编码导致 pip 解析失败的问题。
- 说话人「重命名 / 存为声纹」面板原先内联在 58px 标签列内，溢出压住正文无法点击；
  且同一说话人每句都会弹出一个面板。现改为独立整行、按句绑定。
- 桌面窄窗口/分屏下的多处布局：顶栏按钮溢出压住标题、详情页导出条溢出、纪要页签竖排、
  设置弹窗三列模型名截断、质量中心指标卡挤压、新建任务双列字段过窄。
- 开启鉴权后导出/字幕下载未携带 Bearer 头导致 401（下载改为 fetch + Blob）。

### Changed

- 搜索响应新增 `meta`（分词口径版本）；索引版本落后时搜索页自动提示重建（历史库不误报）。
- 导出/字幕失败路径全部返回可直接展示的中文原因；不支持的格式返回 400 而非静默回退。
- 文档：README 中英新增备份迁移章节；Known limitations 与实现对齐（批量操作、分词提示、
  仅桌面端定位）。

## [1.3.0-s] - 2026-10-23

> Security hardening / 安全加固批次（S1/S2/S3/Q2）。

### Added

- Webhook 出站 SSRF 防护：默认拒绝回环、RFC1918 私网、链路本地与云元数据地址；仅跟随
  一次重定向并在跳转后复检目标；`ASR_WEBHOOK_ALLOWED_HOSTS` / `ASR_WEBHOOK_ALLOW_PRIVATE`
  可按需放行。
- 媒体文件路径 realpath 约束与访问鉴权审计（含冒烟用例：恶意 302、路径越界、媒体鉴权）。
- 启动期安全自检：匿名模式 / 未配置媒体签名密钥时输出 WARNING。

## [1.2.0-d] - 2026-10-23

> Docs / 文档：README 补充 Word(.docx) 导出与 Prometheus 端点说明。

## [1.2.0-c] - 2026-10-23

> Ops & quality / 阶段 C+D（C1/C3/D1）。

### Added

- 运维状态 UI：系统信息、运行时长、AI 网关连通性测试。
- 质量中心：低置信度/过短/重复字等复核队列、批量确认，与转写页低置信度警告联动。
- 最小测试集：pytest 冒烟（匿名/鉴权、存储、检索分词、API 错误语义）与 GitHub Actions CI
  （pytest + 前端构建）。

## [1.2.0-b] - 2026-10-23

> Search UX / 阶段 B（B1/B2/B3）。

### Changed

- 中文检索改用 bigram 分词：专名/词组成为独立 token，BM25 区分度显著提升
  （分词口径变更由搜索页提示重建索引，见 1.4.0）。
- 搜索结果按会议聚合展示，命中定位到具体句子并支持播放跳转；热词文案与新建任务联动。

## [1.2.0-a] - 2026-10-23

> Hardening & docs / 阶段 A（A1/A2/A3）：SSRF 防护收口、文档对齐、生产配置示例。

## [1.1.0] - 2026-10（未打 tag）

> Feature batches P0–P3 / 功能主路径与体验增强。

### Added

- P0：任务进度落库（重启可恢复）、搜索索引异步化（请求路径零扫描 + 后台补建）、
  安全安装引导、依赖锁定与 Docker 部署。
- P1：长会议纪要策略（分块 + 粗摘要 + 低置信度句子排除）、导出（TXT/MD/Word/字幕/复制）、
  混合检索（BM25 + 向量 + RRF + rerank、高亮、facets）、热词与会议级配置。
- P2：多用户隔离补齐、可观测性（events/metrics/Prometheus）、质量中心增强。
- P3：跨会议声纹库（本地存储、可删除、`ASR_VOICEPRINT_ENABLED=0` 可整体关闭）。
- 说话人重命名（本会议内生效，同步全文与检索索引）。

## [1.0.0] - 2026-10-19

> First release / 首个版本。

- 上传（分片/整文件）→ 转写（FunASR Paraformer/SenseVoice，可 GPU）→ 说话人分离（CAM++）
  → 逐句校对 → AI 纪要（多模板）→ 语义检索 → 多格式导出的完整闭环。
- Flask + SQLite 后端、React + Vite 前端、Docker Compose（CPU/GPU profile）、中英 README。

[Unreleased]: https://github.com/loyu123/meetscribe/compare/v1.4.0...HEAD
[1.4.0]: https://github.com/loyu123/meetscribe/compare/v1.3.0-s...v1.4.0
[1.3.0-s]: https://github.com/loyu123/meetscribe/compare/v1.2.0-d...v1.3.0-s
[1.2.0-d]: https://github.com/loyu123/meetscribe/compare/v1.2.0-c...v1.2.0-d
[1.2.0-c]: https://github.com/loyu123/meetscribe/compare/v1.2.0-b...v1.2.0-c
[1.2.0-b]: https://github.com/loyu123/meetscribe/compare/v1.2.0-a...v1.2.0-b
[1.2.0-a]: https://github.com/loyu123/meetscribe/compare/v1.1.0...v1.2.0-a
[1.1.0]: https://github.com/loyu123/meetscribe/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/loyu123/meetscribe/releases/tag/v1.0.0
