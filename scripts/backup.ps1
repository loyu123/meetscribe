# MeetScribe 数据备份（Windows / PowerShell）。
#
# 用法：powershell -ExecutionPolicy Bypass -File scripts\backup.ps1 [-DataDir <路径>] [-OutDir <路径>] [-Keep 14]
#   -DataDir  数据目录，默认 <仓库>\backend\data（即 ASR_DATA_DIR）
#   -OutDir   备份输出目录，默认 <仓库>\backups
#   -Keep     保留最近多少份，默认 14；0 = 不清理
#
# 产出：meetscribe-data-<时间>.zip（data/ 整目录，含 SQLite 与 wal/shm）。
# 建议：备份前先停后端（最稳）；运行中备份的 zip 里的 asr.db 可能包含未合并的
# wal，恢复后如遇数据异常，删除 asr.db-wal / asr.db-shm 再启动即可（WAL 会自动重建）。
#
# 恢复：停后端 → 解压覆盖 data/ → 启动。
param(
  [string]$DataDir = "",
  [string]$OutDir = "",
  [int]$Keep = 14
)
$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
if (-not $DataDir) { $DataDir = Join-Path $repoRoot "backend\data" }
if (-not $OutDir)  { $OutDir  = Join-Path $repoRoot "backups" }

if (-not (Test-Path $DataDir)) {
  throw "[backup] 数据目录不存在: $DataDir"
}
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$ts = Get-Date -Format "yyyyMMdd-HHmmss"
$stage = Join-Path $env:TEMP "meetscribe-bak-$ts"
Copy-Item -Recurse -Force $DataDir $stage

$out = Join-Path $OutDir "meetscribe-data-$ts.zip"
Compress-Archive -Path (Join-Path $stage "*") -DestinationPath $out -Force
Remove-Item -Recurse -Force $stage
Write-Output ("[backup] 已打包: " + $out + " (" + [math]::Round((Get-Item $out).Length / 1MB, 1) + " MB)")

if ($Keep -gt 0) {
  Get-ChildItem $OutDir -Filter "meetscribe-data-*.zip" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -Skip $Keep |
    ForEach-Object {
      Remove-Item $_.FullName -Force
      Write-Output ("[backup] 清理旧备份: " + $_.Name)
    }
}
Write-Output "[backup] 完成。恢复：停后端 → 解压覆盖 data/ → 启动。"
