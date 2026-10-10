import { defineConfig, devices } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import process from 'node:process'

const sha = execFileSync('git', ['rev-parse', 'HEAD'], {encoding: 'utf8'}).trim()
const nativeBase = process.env.YANCE_QA_NATIVE_URL || 'http://127.0.0.1:4175'
export default defineConfig({
  testDir: './e2e',
  timeout: 45_000,
  expect: { timeout: 8_000 },
  forbidOnly: true,
  retries: 0,
  workers: 1,
  fullyParallel: false,
  reporter: [
    ['line'],
    ['json', {outputFile: 'test-results/playwright-results.json'}],
    ['html', {outputFolder: 'test-results/playwright-html', open: 'never'}],
  ],
  outputDir: 'test-results/playwright-artifacts',
  metadata: { sourceSha: sha, viewport:'920x620', fixtureTier:process.env.YANCE_QA_FIXTURE || 'NO_NATIVE_FIXTURE',
    githubRunId:process.env.GITHUB_RUN_ID || 'NOT_CI', githubJob:process.env.GITHUB_JOB || 'NOT_CI',
    githubRepositoryId:process.env.GITHUB_REPOSITORY_ID || 'NOT_CI',
    githubRunAttempt:process.env.GITHUB_RUN_ATTEMPT || 'NOT_CI' },
  use: {
    baseURL: nativeBase,
    viewport: { width: 920, height: 620 },
    headless: true,
    // Required even for passing native cases: W327/W377 independently hash and inspect traces.
    trace: 'on',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
    actionTimeout: 9_000,
  },
  // Native acceptance NEVER starts a synthetic Vite server or proxies production credentials.
  // The isolated app.main + PostgreSQL + authenticated QA environment must be started
  // explicitly by the native QA runner and named by YANCE_QA_NATIVE_URL.
  projects: [
    { name: 'chromium-native', testMatch: /native-critical\.spec\.ts/,
      use: { ...devices['Desktop Chrome'], viewport: {width:920,height:620} } },
    { name: 'chromium-synthetic-bounded', testMatch: /window360-native-channel-modal\.spec\.ts/,
      use: { ...devices['Desktop Chrome'], viewport: {width:920,height:620} } },
  ],
})
