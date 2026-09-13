/* Offline real-Edge checks for knowledge-map.js. No service, user data or model calls.
 * Run: node scripts/check_knowledge_map.cjs
 * Set PLAYWRIGHT_MODULE to an existing Playwright installation when needed.
 * Optional KNOWLEDGE_MAP_QA_DIR selects a new evidence directory.
 */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const repo = path.resolve(__dirname, '..');
const evidenceDirectory = path.resolve(process.env.KNOWLEDGE_MAP_QA_DIR ||
  path.join(repo, '..', 'knowledge-map-qa', new Date().toISOString().replace(/[:.]/g, '-')));
const citation = (changes = {}) => ({source_id: 'synthetic-source-1', author_id: 'synthetic-author',
  title: '合成原文：主动回忆与间隔练习', chunk_index: 0, excerpt: '学习后主动回忆，再按间隔复习。2 < 3。',
  url: 'https://www.zhihu.com/question/123/answer/456', score: 1, ...changes});
const node = (id, label, kind = 'concept', data = {}) => ({id, position: {x: 0, y: 0},
  data: {label, kind, description: '仅供界面测试的合成概念说明。', evidence: [], ...data}});
const edge = (id, source, target, data = {}) => ({id, source, target,
  label: ({supports: '支持', refutes: '反驳', related: '相关', prerequisite: '前置知识',
    qualifies: '限定', supplements: '补充'})[data.relation || 'related'],
  data: {relation: 'related', explanation: '两者在合成资料中共同出现。', evidence: [citation()], ...data}});
const graph = (nodes, edges = [], changes = {}) => ({nodes, edges, total_sources: 3,
  truncated: false, mode: 'openai', classification: '模型根据合成资料提取概念与关系。',
  analysis_notice: '关系仅供整理；请核对引用与适用条件。', ...changes});
const fixtures = {
  classification: graph([
    node('topic:learning', '学习方法', 'topic'),
    node('answer:one', '主动回忆实践', 'answer', {source_id: 'synthetic-source-1'}),
    node('answer:two', '间隔复习计划', 'answer', {source_id: 'synthetic-source-2'}),
  ], [
    {id: 'class:one', source: 'topic:learning', target: 'answer:one', label: '归类', data: null},
    {id: 'class:two', source: 'topic:learning', target: 'answer:two', label: '归类', data: null},
  ], {mode: 'extractive', classification: '按 topics 标签分组；未标注归入未分类。',
    analysis_notice: '分类关系不代表已验证的客观事实。'}),
  concepts: graph([
    node('concept:recall', '主动回忆', 'concept', {evidence: [citation()]}),
    node('concept:spacing', '间隔练习', 'concept', {evidence: [citation({source_id: 'synthetic-source-2'})]}),
    node('concept:transfer', '迁移能力', 'concept', {evidence: [citation()]}),
  ], [edge('relation:prerequisite', 'concept:recall', 'concept:spacing',
    {relation: 'prerequisite', explanation: '先明确回忆目标，再安排练习间隔。'}),
  edge('relation:related', 'concept:spacing', 'concept:transfer')]),
  many: graph(Array.from({length: 61}, (_, index) => node('concept:many-' + index,
    index === 60 ? '末尾可搜索孤立节点61' : '合成概念' + String(index + 1).padStart(2, '0'),
    'concept', {evidence: [citation()]})),
  Array.from({length: 59}, (_, index) => edge('relation:many-' + index,
    'concept:many-0', 'concept:many-' + (index + 1))),
  {total_sources: 100, truncated: true}),
  isolated: graph([node('concept:isolated', '无连线的独立概念', 'concept', {evidence: [citation()]})]),
  empty: graph([], [], {total_sources: 0}),
  malicious: graph([
    node('concept:unsafe', '<img src=x onerror="window.__xss=true">', 'concept', {
      description: '<script>window.__xss=true</script>', evidence: [
        citation({title: '<svg onload="window.__xss=true">', excerpt: '<iframe src=javascript:alert(1)>',
          url: 'javascript:window.__xss=true'}),
        citation({url: 'data:text/html,<script>window.__xss=true</script>'}),
        citation({url: 'https://synthetic-user:synthetic-secret@example.invalid/private'}),
        citation({url: 'https://example.invalid/source'}),
      ]}),
  ]),
};

async function noOverflow(page, name) {
  const dimensions = await page.evaluate(() => ({viewport: innerWidth,
    document: document.documentElement.scrollWidth, body: document.body.scrollWidth}));
  assert.ok(dimensions.document <= dimensions.viewport + 1 && dimensions.body <= dimensions.viewport + 1,
    name + ': horizontal overflow ' + JSON.stringify(dimensions));
  return dimensions;
}

async function render(page, fixture, compact) {
  await page.evaluate(({fixture, compact}) => {
    window.__openedSources = [];
    window.__xss = false;
    window.ZhijingKnowledgeMap.render(document.getElementById('fixture-root'), fixture,
      {compact, onOpenSource: (...args) => window.__openedSources.push(args)});
  }, {fixture, compact});
}

async function main() {
  fs.mkdirSync(evidenceDirectory, {recursive: true});
  const script = fs.readFileSync(path.join(repo, 'src/zhijing/web/knowledge-map.js'), 'utf8');
  const css = fs.readFileSync(path.join(repo, 'src/zhijing/web/knowledge-map.css'), 'utf8');
  const checks = [], pageErrors = [], outboundRequests = [], dialogs = [];
  const browser = await chromium.launch({channel: 'msedge', headless: true});
  let failure;
  try {
    const context = await browser.newContext({acceptDownloads: true, offline: true, serviceWorkers: 'block'});
    await context.route('**/*', route => {outboundRequests.push(route.request().url()); return route.abort();});
    const page = await context.newPage();
    page.on('pageerror', error => pageErrors.push(error.message));
    page.on('dialog', dialog => {dialogs.push(dialog.type()); dialog.dismiss();});
    await page.setContent('<!doctype html><html lang="zh-CN"><meta charset="utf-8">' +
      '<title>合成知识地图验收</title><style>*{box-sizing:border-box}body{margin:0;padding:12px;' +
      'font-family:"Microsoft YaHei UI",system-ui,sans-serif}main{max-width:1160px;margin:auto}</style>' +
      '<main id="fixture-root"></main></html>');
    await page.addStyleTag({content: css});
    await page.addScriptTag({content: script});
    assert.equal(await page.evaluate(() => typeof window.ZhijingKnowledgeMap?.render), 'function');
    // Component-specific interaction assertions are kept in one bounded matrix below.
    await runMatrix(page, checks);
    assert.deepEqual(pageErrors, [], 'No browser JavaScript errors');
    assert.deepEqual(dialogs, [], 'Fixture content must never execute');
    assert.deepEqual(outboundRequests, [], 'No external resources may be requested');
  } catch (error) {
    failure = error;
  } finally {
    await browser.close();
    const report = {passed: !failure, browser: 'Microsoft Edge', checks,
      pageErrors, dialogs, outboundRequests, synthetic_only: true,
      ...(failure ? {error: failure.stack || String(failure)} : {})};
    fs.writeFileSync(path.join(evidenceDirectory, 'report.json'), JSON.stringify(report, null, 2));
  }
  if (failure) throw failure;
  console.log(JSON.stringify({passed: true, count: checks.length, evidenceDirectory}));
}

async function runMatrix(page, checks) {
  for (const width of [1200, 480, 364]) {
    await page.setViewportSize({width, height: 900});
    const compact = width < 600;
    const check = async (name, action) => {
      await action();
      checks.push({name, width, ...await noOverflow(page, name)});
    };
    const selected = async id => assert.equal(await page.locator('.km-node.is-selected').getAttribute('data-node-id'), id);
    const sourceOpened = async sourceId => assert.deepEqual(await page.evaluate(() => window.__openedSources), [[sourceId]]);

    await render(page, fixtures.classification, compact);
    await check('classification diagram and original-source callback', async () => {
      assert.match(await page.locator('.km-eyebrow').first().innerText(), /资料分类图/);
      assert.match(await page.locator('.km-count').innerText(), /3 个节点.*2 条关系/);
      await selected('topic:learning');
      await page.locator('.km-relations .km-relation').first().click();
      assert.match(await page.locator('.km-description').innerText(), /归类.*不表示因果、支持或反驳/);
      await page.getByRole('button', {name: '查看 主动回忆实践', exact: true}).click();
      await selected('answer:one');
      await page.locator('.km-open-source').click();
      await sourceOpened('synthetic-source-1');
    });

    await render(page, fixtures.concepts, compact);
    await check('concept click, Enter focus, relation explanation and evidence', async () => {
      assert.match(await page.locator('.km-eyebrow').first().innerText(), /概念关系图/);
      await page.locator('.km-node[data-node-id="concept:recall"]').click();
      await selected('concept:recall');
      await page.locator('.km-node[data-node-id="concept:spacing"]').focus();
      await page.keyboard.press('Enter');
      await selected('concept:spacing');
      assert.equal(await page.evaluate(() => document.activeElement.getAttribute('data-node-id')), 'concept:spacing');
      assert.equal(await page.locator('.km-detail h3').innerText(), '间隔练习');
      await page.locator('.km-relations .km-relation').filter({hasText: '前置知识'}).click();
      assert.match(await page.locator('.km-description').innerText(), /先明确回忆目标/);
      await page.locator('.km-citation summary').first().click();
      assert.match(await page.locator('.km-citation blockquote').first().innerText(), /2 < 3/);
      await page.locator('.km-citation .km-open-source').first().click();
      await sourceOpened('synthetic-source-1');
      const link = page.locator('.km-citation a').first();
      assert.equal(await link.getAttribute('href'), citation().url);
      assert.match(await link.getAttribute('rel'), /noopener/);
      await page.getByRole('button', {name: '查看 主动回忆', exact: true}).click();
      await selected('concept:recall');
    });
    await check('zoom and reset', async () => {
      const initial = await page.locator('.km-canvas').getAttribute('viewBox');
      await page.locator('.km-zoom-in').click();
      assert.notEqual(await page.locator('.km-canvas').getAttribute('viewBox'), initial);
      assert.equal(await page.locator('.km-zoom-label').innerText(), '125%');
      await page.locator('.km-zoom-out').click();
      await page.locator('.km-zoom-in').click();
      await page.locator('.km-reset').click();
      assert.equal(await page.locator('.km-canvas').getAttribute('viewBox'), initial);
      assert.equal(await page.locator('.km-zoom-label').innerText(), '100%');
    });
    const renderedFont = await page.locator('.km-node-label').first().evaluate(node => {
      const matrix = node.getScreenCTM();
      return parseFloat(getComputedStyle(node).fontSize) * Math.hypot(matrix.a, matrix.b);
    });
    checks.push({name: 'effective diagram label pixels', width, pixels: renderedFont});
    await page.screenshot({path: path.join(evidenceDirectory, 'concepts-' + width + '.png'), fullPage: true});

    await render(page, fixtures.many, compact);
    await check('all 61 nodes reachable via list pagination', async () => {
      assert.ok(await page.locator('.km-node').count() < fixtures.many.nodes.length);
      assert.equal(await page.locator('.km-node').count(), compact ? 7 : 18);
      assert.match(await page.locator('.km-diagram-status').innerText(), /部分相邻节点未绘出/);
      assert.equal(await page.locator('.km-node[data-node-id="concept:many-60"]').count(), 0);
      const cards = await page.locator('.km-node rect').evaluateAll(nodes => nodes.map(node => {
        const rect = node.getBoundingClientRect();
        return {id: node.parentElement.dataset.nodeId, left: rect.left, right: rect.right,
          top: rect.top, bottom: rect.bottom};
      }));
      await page.locator('.km-diagram').screenshot({path: path.join(evidenceDirectory, 'star-diagram-' + width + '.png')});
      for (let i = 0; i < cards.length; i++) for (let j = i + 1; j < cards.length; j++) {
        const a = cards[i], b = cards[j];
        const overlapWidth = Math.min(a.right, b.right) - Math.max(a.left, b.left);
        const overlapHeight = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
        assert.ok(overlapWidth <= .5 || overlapHeight <= .5,
          `Star nodes overlap at ${width}px: ${a.id}, ${b.id}: ${overlapWidth} x ${overlapHeight}`);
      }
      await page.locator('.km-view-list').click();
      assert.equal(await page.locator('.km-node-item').count(), 20);
      for (let step = 0; step < 3; step++) await page.locator('.km-load-more').click();
      const ids = await page.locator('.km-node-item').evaluateAll(nodes => nodes.map(node => node.dataset.nodeId));
      assert.deepEqual(ids, fixtures.many.nodes.map(node => node.id));
    });
    await check('search beyond diagram cap and focus an isolated node', async () => {
      await page.locator('input.km-search').fill('末尾可搜索孤立节点61');
      assert.equal(await page.locator('.km-node-item').count(), 1);
      await page.locator('.km-node-item').click();
      await selected('concept:many-60');
      assert.equal(await page.locator('.km-node').count(), 1);
      assert.match(await page.locator('.km-relations').innerText(), /没有.*相连/);
      assert.match(await page.locator('.km-diagram-status').innerText(), /1 \/ 61/);
      await page.locator('input.km-search').fill('肯定不存在的合成查询');
      assert.equal(await page.locator('.km-node-item').count(), 0);
      assert.match(await page.locator('.km-empty-search').innerText(), /没有匹配/);
    });
    await check('JSON download preserves the full graph while filtered', async () => {
      const [download] = await Promise.all([page.waitForEvent('download'), page.locator('.km-export').click()]);
      const file = path.join(evidenceDirectory, 'full-graph-' + width + '.json');
      await download.saveAs(file);
      assert.deepEqual(JSON.parse(fs.readFileSync(file, 'utf8')), fixtures.many);
    });
    await page.locator('.km-view-list').click();
    await page.locator('input.km-search').fill('');
    await page.screenshot({path: path.join(evidenceDirectory, 'nodes-' + width + '.png'), fullPage: true});

    await render(page, fixtures.isolated, compact);
    await check('isolated graph', async () => {
      assert.equal(await page.locator('.km-node').count(), 1);
      assert.equal(await page.locator('.km-edge').count(), 0);
      assert.match(await page.locator('.km-detail').innerText(), /没有.*相连/);
    });
    await render(page, fixtures.empty, compact);
    await check('empty graph', async () => {
      assert.equal(await page.locator('.km-node').count(), 0);
      assert.match(await page.locator('.km-empty').innerText(), /没有可展示的节点/);
      assert.match(await page.locator('.km-count').innerText(), /0 个节点.*0 条关系/);
    });
    await render(page, fixtures.malicious, compact);
    await check('literal XSS text and safe source URLs', async () => {
      for (const summary of await page.locator('.km-citation summary').all()) await summary.click();
      assert.equal(await page.locator('.km-detail h3').innerText(), fixtures.malicious.nodes[0].data.label);
      assert.equal(await page.locator('.km-detail img,.km-detail script,.km-detail iframe,.km-detail svg').count(), 0);
      const hrefs = await page.locator('.km-detail a').evaluateAll(nodes => nodes.map(node => node.href));
      assert.deepEqual(hrefs, ['https://example.invalid/source']);
      assert.equal(await page.evaluate(() => window.__xss), false);
    });
  }
}

main().catch(error => {console.error(error.stack || error); process.exitCode = 1;});
