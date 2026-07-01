#!/usr/bin/env node
/**
 * validate-openrouter.mjs
 * ------------------------------------------------------------------
 * Cheap connectivity check for OpenRouter using a FREE/open-source model.
 * - Reads OPENROUTER_API_KEY and model config from the environment (.env).
 * - Makes ONE minimal chat completion call against a free model.
 * - Prints PASS/FAIL. NEVER prints the API key.
 *
 * Usage:
 *   node scripts/validate-openrouter.mjs
 *   (ensure your .env has a real OPENROUTER_API_KEY first)
 *
 * Exit codes: 0 = success, 1 = misconfiguration, 2 = API error.
 */

import fs from 'node:fs';
import path from 'node:path';

// --- Minimal .env loader (no dependency) ---------------------------------
function loadEnv() {
  const envPath = path.resolve(process.cwd(), '.env');
  if (fs.existsSync(envPath)) {
    for (const raw of fs.readFileSync(envPath, 'utf8').split('\n')) {
      const line = raw.trim();
      if (!line || line.startsWith('#')) continue;
      const idx = line.indexOf('=');
      if (idx === -1) continue;
      const key = line.slice(0, idx).trim();
      const val = line.slice(idx + 1).trim();
      if (!(key in process.env)) process.env[key] = val;
    }
  }
}

loadEnv();

const KEY = process.env.OPENROUTER_API_KEY;
const BASE = process.env.OPENROUTER_BASE_URL || 'https://openrouter.ai/api/v1';
const MODEL = process.env.AETHER_MODEL_LIGHT || 'meta-llama/llama-3.1-8b-instruct:free';

function fail(code, msg) {
  console.error(`\n❌ OpenRouter validation FAILED: ${msg}\n`);
  process.exit(code);
}

if (!KEY || KEY.includes('REPLACE_WITH_YOUR_REAL')) {
  fail(
    1,
    'OPENROUTER_API_KEY is missing or still a placeholder.\n' +
      '   → Edit .env and paste a real key from https://openrouter.ai/keys'
  );
}

console.log(`• Endpoint : ${BASE}`);
console.log(`• Model    : ${MODEL} (free tier)`);
console.log('• Key      : present (hidden)');
console.log('• Sending a 1-token ping...');

try {
  const res = await fetch(`${BASE}/chat/completions`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${KEY}`,
      'Content-Type': 'application/json',
      'HTTP-Referer':
        process.env.OPENROUTER_HTTP_REFERER ||
        'https://github.com/Victordtesla24/aether-job-career-agent',
      'X-Title': process.env.OPENROUTER_APP_TITLE || 'Aether',
    },
    body: JSON.stringify({
      model: MODEL,
      messages: [{ role: 'user', content: 'Reply with the single word: OK' }],
      max_tokens: 5,
      temperature: 0,
    }),
  });

  if (!res.ok) {
    const text = await res.text();
    fail(2, `HTTP ${res.status} — ${text.slice(0, 300)}`);
  }

  const data = await res.json();
  const reply = data?.choices?.[0]?.message?.content?.trim() ?? '(no content)';
  console.log(`\n✅ OpenRouter reachable. Model replied: "${reply}"`);
  console.log('   You are ready to run Aether tests against free models.\n');
  process.exit(0);
} catch (err) {
  fail(2, err?.message || String(err));
}
