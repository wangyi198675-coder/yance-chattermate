import { beforeEach, describe, expect, it, vi } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const { apiGet, apiPost, setCurrentUser } = vi.hoisted(() => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  setCurrentUser: vi.fn(),
}))

vi.mock('@/services/api', () => ({
  default: { get: apiGet, post: apiPost },
}))

vi.mock('@/services/user', () => ({
  userService: { setCurrentUser },
}))

import {
  classifySetupFailure,
  getSetupStatus,
  privateBootstrap,
} from '@/services/organization'

describe('Window92 private bootstrap setup state', () => {
  beforeEach(() => {
    apiGet.mockReset()
    apiPost.mockReset()
    setCurrentUser.mockReset()
  })

  it('projects READY only from a successful setup response', async () => {
    apiGet.mockResolvedValue({ data: { is_setup: true } })
    await expect(getSetupStatus()).resolves.toBe('READY')
  })

  it('projects SETUP_INCOMPLETE only from a successful no-organization response', async () => {
    apiGet.mockResolvedValue({ data: { is_setup: false } })
    await expect(getSetupStatus()).resolves.toBe('SETUP_INCOMPLETE')
  })

  it('projects backend HTTP 500 as BACKEND_UNAVAILABLE', async () => {
    apiGet.mockRejectedValue({ response: { status: 500 } })
    await expect(getSetupStatus()).resolves.toBe('BACKEND_UNAVAILABLE')
  })

  it('projects transport failure as NETWORK_ERROR', async () => {
    apiGet.mockRejectedValue({ request: {}, message: 'Network Error' })
    await expect(getSetupStatus()).resolves.toBe('NETWORK_ERROR')
    expect(classifySetupFailure({ request: {} })).toBe('NETWORK_ERROR')
  })

  it('adopts native private bootstrap user into the existing user service', async () => {
    const user = { id: 'u1', email: 'local-admin@yance.invalid', full_name: 'Yance Local Admin' }
    apiPost.mockResolvedValue({ data: { id: 'o1', user } })
    await privateBootstrap()
    expect(apiPost).toHaveBeenCalledWith('/organizations/private-bootstrap')
    expect(setCurrentUser).toHaveBeenCalledWith(user)
  })

  it('keeps login/setup out of the private main path and routes failures truthfully', () => {
    const routerSource = readFileSync(resolve(process.cwd(), 'src/router/index.ts'), 'utf8')
    const apiSource = readFileSync(resolve(process.cwd(), 'src/services/api.ts'), 'utf8')

    expect(routerSource).toContain("redirect: '/yance'")
    expect(routerSource).toContain("name: 'yance-startup-state'")
    expect(routerSource).toContain("setupState === 'SETUP_INCOMPLETE'")
    expect(routerSource).toContain("setupState === 'BACKEND_UNAVAILABLE'")
    expect(routerSource).toContain("setupState === 'NETWORK_ERROR'")
    expect(routerSource).not.toContain("next('/setup')")
    expect(routerSource).not.toContain("path: '/login', query")
    expect(apiSource).not.toContain("router.push('/login')")
  })
})