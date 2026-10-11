import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'

const here = path.dirname(fileURLToPath(import.meta.url))
const specPath = path.resolve(here, '../../src/__tests__/webclient/widgetComposer.spec.ts')
const requiredTests = [
  'ignores queued PREFILL_MESSAGE callback after unmount',
  'cancels initialization polling when unmounted without widgetId',
]

function callTarget(expression) {
  const modifiers = []
  while (ts.isPropertyAccessExpression(expression)) {
    modifiers.unshift(expression.name.text)
    expression = expression.expression
  }
  if (!ts.isIdentifier(expression)) return null
  return { base: expression.text, modifiers }
}

function declarations(source) {
  const root = ts.createSourceFile('widgetComposer.spec.ts', source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
  if (root.parseDiagnostics.length) throw Error('W393_TEST_SOURCE_TYPESCRIPT_PARSE_ERROR')
  const seen = new Map(requiredTests.map(name => [name, 0]))

  function walk(node, blocked) {
    let blockedChildren = blocked
    if (ts.isCallExpression(node)) {
      const target = callTarget(node.expression)
      if (target) {
        if (target.base === 'describe' && target.modifiers.length > 0) {
          blockedChildren = true
        }
        if ((target.base === 'it' || target.base === 'test') && target.modifiers.length === 0 && !blocked) {
          const title = node.arguments[0]
          if (title && (ts.isStringLiteral(title) || ts.isNoSubstitutionTemplateLiteral(title))) {
            if (seen.has(title.text)) seen.set(title.text, seen.get(title.text) + 1)
          }
        }
      }
    }
    ts.forEachChild(node, child => walk(child, blockedChildren))
  }
  walk(root, false)
  return requiredTests.filter(name => seen.get(name) !== 1)
}

function verifyVitestJSON(raw) {
  const data = JSON.parse(raw)
  if (!Array.isArray(data.testResults)) throw Error('W393_VITEST_REPORT_MISSING_TEST_RESULTS')
  const reported = data.testResults.filter(t => /widgetComposer\.spec\.ts$/i.test(String(t.name || '').replace(/\\/g, '/')))
  if (reported.length !== 1) throw Error('W393_VITEST_SPEC_REPORT_NOT_UNIQUE')
  const assertions = reported[0].assertionResults
  if (!Array.isArray(assertions)) throw Error('W393_VITEST_REPORT_MISSING_ASSERTIONS')
  const failed = requiredTests.filter(name => {
    const rows = assertions.filter(a => a.title === name && typeof a.fullName === 'string')
    return rows.length !== 1 || rows[0].status !== 'passed'
  })
  if (failed.length) throw Error('W393_VITEST_REQUIRED_TESTS_NOT_BOTH_PASSED: ' + failed.join(' | '))
  if (data.success !== true || Number(data.numFailedTests) !== 0 || Number(data.numPendingTests) !== 0) {
    throw Error('W393_VITEST_FOCUSED_REPORT_NOT_GREEN_OR_HAS_SKIPS')
  }
  return true
}

function check(condition, description) {
  if (!condition) throw Error('W393_GATE_SELFTEST_FAILED: ' + description)
}

if (process.argv.includes('--selftest')) {
  const declaration = name => 'it(' + JSON.stringify(name) + ', () => { expect(1).toBe(1) })'
  const good = requiredTests.map(declaration).join('\n')
  check(declarations(good).length === 0, 'valid declarations')
  for (const name of requiredTests) {
    check(declarations(good.replace(declaration(name), '')).includes(name), 'removed '+ name)
    check(declarations(good.replace(declaration(name), '// ' + declaration(name))).includes(name), 'commented '+name)
    check(declarations(good.replace(declaration(name), declaration(name).replace(/^it\(/, 'it.skip('))).includes(name), 'it.skip '+name)
    check(declarations(good.replace(declaration(name), 'describe.skip("parent", () => { ' + declaration(name) + ' })')).includes(name), 'describe.skip '+name)
    check(declarations(good.replace(declaration(name), 'describe.only("parent", () => { ' + declaration(name) + ' })')).includes(name), 'describe.only '+name)
    check(declarations(good.replace(declaration(name), JSON.stringify(declaration(name)))).includes(name), 'string pseudo-test '+name)
  }
  const report = statuses => JSON.stringify({
    success: true,
    numFailedTests: 0,
    numPendingTests: 0,
    testResults: [{
      name: 'C:/qa/widgetComposer.spec.ts',
      assertionResults: requiredTests.map((name, i) => ({
        title: name, fullName: 'widget / ' + name, status: statuses[i]
      }))
    }]
  })
  check(verifyVitestJSON(report(['passed','passed'])), 'both executed and PASS')
  for (const bad of [['passed','pending'], ['failed','passed'], ['passed','skipped']]) {
    let threw = false
    try { verifyVitestJSON(report(bad)) } catch { threw = true }
    check(threw, 'reject '+bad)
  }
  console.log('W393_AST_AND_REAL_VITEST_JSON_GATE_NEGATIVE_SELFTEST_PASS')
  process.exit(0)
}

const reportOption = process.argv.find(arg => arg.startsWith('--verify-results='))
if (reportOption) {
  verifyVitestJSON(fs.readFileSync(reportOption.slice('--verify-results='.length), 'utf8'))
  console.log('W393_REQUIRED_TWO_NEGATIVE_TESTS_EXECUTED_AND_PASSED_IN_REAL_VITEST')
} else {
  const absent = declarations(fs.readFileSync(specPath, 'utf8'))
  if (absent.length) {
    console.error('W393_REQUIRED_TEST_DECLARATIONS_MISSING_COMMENTED_SKIPPED_OR_DUPLICATE: ' + absent.join(' | '))
    process.exit(1)
  }
  console.log('W393_REQUIRED_TEST_DECLARATIONS_VALID_AST; real Vitest JSON must still pass')
}
