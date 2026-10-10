import { expect, test } from '@playwright/test'
import { mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

const origin = process.env.W360_QA_URL || 'http://127.0.0.1:4181'
const screenshotDir = process.env.W360_QA_DIR || 'test-results'
const channels = ['email', 'sms', 'line'] as const

test('W360 native Email/SMS/LINE modals fit 920x620 and close without provider mutations', async ({ page }) => {
  const mutations: string[] = []
  const errors: string[] = []
  const measurements: Record<string, unknown>[] = []
  page.on('pageerror', err => errors.push(err.message))
  await page.setViewportSize({ width: 920, height: 620 })

  const accounts = channels.map(channel => ({
    id: 'w360-existing-' + channel,
    channel_type: channel,
    external_account_id: 'w360-test-only-' + channel,
    display_name: 'W360 synthetic ' + channel,
    is_active: true,
    provider_health: { readiness: 'ready' },
  }))
  await page.route('**/api/v1/channels/**', async route => {
    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(route.request().method())) {
      mutations.push(route.request().method() + ' ' + route.request().url())
      await route.fulfill({ status: 403, contentType: 'application/json', body: '{"detail":"Blocked W360 QA"}' })
    } else {
      await route.continue()
    }
  })
  await page.route('**/api/v1/channels/accounts*', async route => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(accounts) })
  })

  await page.goto(origin + '/yance/home')
  await expect(page.locator('[data-yance-home-native-composition]')).toBeVisible()
  await page.locator('button.nav-link:has-text("人物")').click()
  await expect(page).toHaveURL(/\/yance\/people$/)
  await expect(page.getByText('AI Agents', { exact: true })).toHaveCount(0)
  await page.goto(origin + '/yance/settings')
  await page.locator('a:has-text("管理平台账号")').click()
  await expect(page).toHaveURL(/\/yance\/platform-accounts$/)
  await expect(page.locator('[data-platform-type="email"] li').first()).toBeVisible()
  mkdirSync(screenshotDir, { recursive: true })

  for (const channel of channels) {
    const section = page.locator('[data-platform-type="' + channel + '"]')
    await section.locator('li').first().getByRole('button', { name: '查看账号' }).click()
    const safe = page.locator('[data-yance-existing-credential-safe-view]')
    await expect(safe).toContainText('w360-test-only-' + channel)
    await expect(page.locator('.cc-modal')).toHaveCount(0)
    await safe.getByRole('button', { name: '关闭' }).click()

    const add = section.locator('header button:has-text("添加账号")')
    await add.click()
    const modal = page.locator('.cc-modal')
    await expect(modal).toBeVisible()
    const panel = modal.locator('.cc-modal-content')
    const close = modal.locator('.cc-close-btn')
    const panelRect = await panel.boundingBox()
    const closeRect = await close.boundingBox()
    const measurement: Record<string, unknown> = { channel, panel: panelRect, close: closeRect }
    measurements.push(measurement)
    expect(panelRect, channel + ' panel measured').not.toBeNull()
    expect(closeRect, channel + ' close measured').not.toBeNull()
    expect(panelRect!.y).toBeGreaterThanOrEqual(0)
    expect(panelRect!.y + panelRect!.height).toBeLessThanOrEqual(620)
    expect(closeRect!.y).toBeGreaterThanOrEqual(0)
    expect(closeRect!.y + closeRect!.height).toBeLessThanOrEqual(620)
    await page.screenshot({ path: join(screenshotDir, 'w360_' + channel + '_open_920x620.png') })

    await close.click()
    await expect(modal).toHaveCount(0)
    await add.click()
    await expect(modal).toBeVisible()
    const body = modal.locator('.cc-modal-body')
    const dimensions = await body.evaluate(el => ({
      scrollHeight: el.scrollHeight, clientHeight: el.clientHeight,
    }))
    await body.evaluate(el => { el.scrollTop = el.scrollHeight })
    const scrolled = await body.evaluate(el => el.scrollTop)
    measurement.body = dimensions
    measurement.scrolled = scrolled
    if (channel === 'email') {
      expect(dimensions.scrollHeight).toBeGreaterThan(dimensions.clientHeight)
      expect(scrolled).toBeGreaterThan(0)
    } else if (dimensions.scrollHeight > dimensions.clientHeight) {
      expect(scrolled).toBeGreaterThan(0)
    }
    const lastInput = modal.locator('.cc-field input').last()
    await lastInput.scrollIntoViewIfNeeded()
    const lastRect = await lastInput.boundingBox()
    expect(lastRect, channel + ' final field').not.toBeNull()
    expect(lastRect!.y).toBeGreaterThanOrEqual(0)
    expect(lastRect!.y + lastRect!.height).toBeLessThanOrEqual(620)
    await page.screenshot({ path: join(screenshotDir, 'w360_' + channel + '_scroll_920x620.png') })
    await modal.getByRole('button', { name: 'Cancel' }).click()
    await expect(modal).toHaveCount(0)

    await add.click()
    await expect(modal).toBeVisible()
    await page.keyboard.press('Escape')
    await expect(modal).toHaveCount(0)
  }

  expect(mutations).toEqual([])
  expect(errors).toEqual([])
  writeFileSync(join(screenshotDir, 'w360_modal_metrics.json'), JSON.stringify({
    origin, viewport: { width: 920, height: 620 }, measurements,
    providerMutations: mutations, pageErrors: errors,
  }, null, 2))
})
