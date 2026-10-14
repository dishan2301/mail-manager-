const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const ts = require('typescript');

test('ProductionApp invokes all hooks before any early return', () => {
  const source = ts.createSourceFile('ProductionApp.tsx', fs.readFileSync(path.join(__dirname, '../src/ProductionApp.tsx'), 'utf8'), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const component = source.statements.find(node => ts.isFunctionDeclaration(node) && node.name?.text === 'ProductionApp');
  assert.ok(component?.body, 'ProductionApp component was not found');
  let returned = false;
  function visit(node) {
    if (ts.isFunctionLike(node)) return;
    if (ts.isReturnStatement(node)) returned = true;
    if (ts.isCallExpression(node) && ts.isIdentifier(node.expression) && /^use[A-Z]/.test(node.expression.text)) {
      assert.equal(returned, false, `${node.expression.text} is called after a possible early return`);
    }
    ts.forEachChild(node, visit);
  }
  component.body.statements.forEach(visit);
});
