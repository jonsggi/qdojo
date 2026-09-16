// Dependency-free, no browser/network needed. Demonstrates current defects;
// these assertions should fail after the corresponding issues are fixed.
// Run: node audits/probes/browser_findings.cjs
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const { webcrypto } = require('node:crypto');
const web = path.resolve(__dirname, '../../apps/web');
const source = fs.readFileSync(path.join(web, 'app.js'), 'utf8');
const boot = source.indexOf('// ---------------------------------------------------------------- boot');
assert.ok(boot > 0);
const output = { innerHTML: '' };
const context = vm.createContext({
  TextEncoder, crypto: webcrypto, window: { crypto: webcrypto },
  document: { querySelector: () => output },
});
vm.runInContext(source.slice(0, boot), context); // load helpers without boot/fetch/timers
const run = code => vm.runInContext(code, context);

(async () => {
  const pot = run(`livePot({house_seed: 5000, match_bps: 10000, carry_in: 0,
    house_fighters: ['HOUSE_BOT'], entries: [{identity: 'HOUSE_BOT', verdict: 'pending', stake: 1000}]})`);
  assert.equal(pot, 2000);
  console.log('AUD-007: browser shows 2,000 QU for a 1,000-QU house-only stake; rules require 1,000');

  const { rounds } = JSON.parse(fs.readFileSync(path.join(web, 'data/history.json'), 'utf8'));
  context.round = structuredClone(rounds.find(r => r.settlement && !r.settlement.void));
  assert.ok(context.round);
  // Change settlement money without changing payouts, then update the same-source hash.
  context.round.settlement.pot += 1;
  await run(`(async () => {
    round.settlement.hash = await settlementHash(round.settlement);
    S.data = {rounds: [round]};
    await runVerify(round.round_id);
  })()`);
  assert.ok(output.innerHTML.includes('THE HOUSE DID NOT MOVE THE GOALPOSTS'));
  console.log('AUD-008: altered pot plus replacement hash still gets the strong verification claim');
  await run(`(async () => { S.data = {rounds: [{round_id: 999}]}; await runVerify(999); })()`);
  assert.ok(output.innerHTML.includes('ALL CHECKS PASS'));
  console.log('AUD-008: no applicable checks also produces ALL CHECKS PASS');
})().catch(error => { console.error(error); process.exitCode = 1; });
