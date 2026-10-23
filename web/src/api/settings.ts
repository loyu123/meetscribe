import { getJSON, postJSON, putJSON } from './client'

/** AI 网关配置（后端 runtime_settings 模块；密钥掩码返回） */
export interface GatewaySettings {
  gateway_url: string
  gateway_token_masked: string
  token_set: boolean
  llm_model: string
  embed_model: string
  rerank_model: string
}

export function getGateway(): Promise<GatewaySettings> {
  return getJSON<GatewaySettings>('/settings')
}

/** 保存网关配置；token 传空字符串表示不修改现有密钥 */
export function saveGateway(p: Partial<GatewaySettings> & { gateway_token?: string }) {
  return putJSON<{ ok: boolean; changed: string[]; settings: GatewaySettings }>('/settings', p)
}

/** 探测网关连通性（GET /models），返回可用模型列表 */
export function testGateway(): Promise<{ ok: boolean; models: string[] }> {
  return postJSON<{ ok: boolean; models: string[] }>('/settings/test')
}

/** 系统信息（用户菜单信息条 / 关于弹层 / 安全引导） */
export interface SystemInfo {
  version: string
  brand: string
  brand_zh: string
  recordings: number
  storage_bytes: number
  status: string
  /** 安全配置状态（P0-3），旧版后端可能不返回 */
  auth_configured?: boolean
  media_sign_enabled?: boolean
  gateway_configured?: boolean
}

export function getSystemInfo(): Promise<SystemInfo> {
  return getJSON<SystemInfo>('/system')
}
