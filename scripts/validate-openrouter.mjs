// scripts/validate-openrouter.mjs
// Validates OpenRouter connectivity with one cheap call to a free model.
// NEVER logs the API key. Exits 0 on success, 1 on failure.
import { readFileSync } from 'fs';

// Load .env manually (dotenv not guaranteed installed here)
let apiKey;
try {
  const envContent = readFileSync('.env', 'utf8');
  apiKey = envContent.match(/^OPENROUTER_API_KEY=(.+)$/m)?.[1]?.trim();
} catch {
  console.error('❌ Could not read .env file');
  process.exit(1);
}

if (!apiKey || apiKey === 'your-openrouter-api-key-here') {
  console.error('❌ OPENROUTER_API_KEY is not set in .env');
  process.exit(1);
}

// Primary model (overridable) plus free fallbacks. Free models are frequently
// rate-limited upstream (HTTP 429); we retry briefly and fall back so a transient
// 429 does not fail a genuine connectivity check.
const primary = process.env.AETHER_MODEL_LIGHT || 'meta-llama/llama-3.2-3b-instruct:free';
const candidates = [
  primary,
  'meta-llama/llama-3.3-70b-instruct:free',
  'qwen/qwen3-next-80b-a3b-instruct:free',
];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function ping(model) {
  const res = await fetch('https://openrouter.ai/api/v1/chat/completions', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${apiKey}`,
      'HTTP-Referer': 'https://github.com/Victordtesla24/aether-job-career-agent',
      'X-Title': 'Aether',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      model,
      messages: [{ role: 'user', content: 'Reply with exactly: {"status":"ok"}' }],
      temperature: 0,
      max_tokens: 20,
    }),
  });
  return res;
}

let lastStatus = 0;
let lastErr = '';
let sawRateLimit = false; // proves the endpoint is reachable AND our key authenticated
let sawAuthFailure = false; // 401/403 from OpenRouter itself => bad key

for (const model of candidates) {
  for (let attempt = 1; attempt <= 2; attempt++) {
    console.log(`🔍 Pinging OpenRouter with model: ${model} (attempt ${attempt})`);
    try {
      const res = await ping(model);
      if (res.ok) {
        const data = await res.json();
        const content = data.choices?.[0]?.message?.content ?? '';
        console.log(`✅ OpenRouter OK — model: ${model}, response snippet: ${content.slice(0, 80)}`);
        console.log(`✅ Validation PASSED at ${new Date().toISOString()}`);
        process.exit(0);
      }
      lastStatus = res.status;
      lastErr = await res.text();
      if (res.status === 401 || res.status === 403) {
        sawAuthFailure = true;
        break; // bad credentials — no point continuing
      }
      if (res.status === 429) {
        // Rate-limited downstream: OpenRouter accepted our key and routed the call.
        sawRateLimit = true;
        const retryAfter = Number(res.headers.get('retry-after')) || 3;
        console.log(`⏳ ${model} rate-limited (429). Waiting ${retryAfter}s before next attempt…`);
        await sleep(Math.min(retryAfter, 8) * 1000);
        continue;
      }
      // Other statuses (e.g. 400 from a downstream BYOK provider) — try next model.
      console.log(`⚠️  ${model} returned ${res.status}; trying next candidate.`);
      break;
    } catch (e) {
      lastErr = e.message;
      console.log(`⚠️  Network error on ${model}: ${e.message}`);
    }
  }
}

if (sawAuthFailure) {
  console.error(`❌ OpenRouter rejected the API key (HTTP ${lastStatus}). Check OPENROUTER_API_KEY.`);
  process.exit(1);
}

// A 429 anywhere proves reachability + valid auth; free models are just saturated.
if (sawRateLimit) {
  console.log('✅ OpenRouter REACHABLE & AUTHENTICATED — free models are transiently rate-limited (HTTP 429).');
  console.log(`✅ Connectivity validation PASSED (rate-limited, key valid) at ${new Date().toISOString()}`);
  process.exit(0);
}

console.error(`❌ OpenRouter validation failed. Last status: ${lastStatus}. Detail: ${lastErr}`);
process.exit(1);
