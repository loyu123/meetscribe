// 侧栏文件夹（与后端 recordings.folder 字段对应，'' 表示未归类）
export const FOLDERS = ['项目复盘', '客户访谈'] as const

// 本地设置键（设置弹层持久化）
export const SETTINGS_KEY = 'lingyu_settings'
export const ASK_FOLD_KEY = 'lingyu_ask_folded'

export interface AppSettings {
  theme: string
  model: string
  hotwords: string
  speakers: string
}

export const DEFAULT_SETTINGS: AppSettings = { theme: 'light', model: 'paraformer', hotwords: '', speakers: '' }

export function loadSettings(): AppSettings {
  try {
    return { ...DEFAULT_SETTINGS, ...JSON.parse(localStorage.getItem(SETTINGS_KEY) || '{}') }
  } catch {
    return { ...DEFAULT_SETTINGS }
  }
}

export function saveSettings(s: AppSettings) {
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(s))
}
