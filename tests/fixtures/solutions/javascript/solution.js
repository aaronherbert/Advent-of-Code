const n = require('fs').readFileSync(0, 'utf8').split(/\s+/).filter(Boolean).map(Number);
console.log(n.reduce((a, b) => a + b, 0));
console.log(n.reduce((a, b) => a + b * b, 0));
