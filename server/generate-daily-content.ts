/**
 * Spirit Series Platform — Daily Content Generator
 * -------------------------------------------------
 * Generates today's Daily Prayer, Word of the Day (Greek/Hebrew),
 * and (on Sundays) the weekly Short Sermon.
 *
 * All content is attributed to "Rev Fab fire" as per platform policy.
 * Content is saved to /content/daily/<YYYY-MM-DD>.json and a
 * human-readable Markdown file at /content/daily/<YYYY-MM-DD>.md
 *
 * Usage:
 *   cd /home/ubuntu/spirit-series-platform
 *   npx tsx server/generate-daily-content.ts
 */

import fs from "fs";
import path from "path";
import OpenAI from "openai";

// ─── Configuration ───────────────────────────────────────────────────────────

const AUTHOR = "Rev Fab fire";
const CONTENT_DIR = path.resolve(__dirname, "../content/daily");
const MODEL = "gpt-4o";

// ─── Helpers ─────────────────────────────────────────────────────────────────

function getTodayISO(): string {
  return new Date().toISOString().split("T")[0]; // YYYY-MM-DD
}

function isSunday(): boolean {
  return new Date().getDay() === 0;
}

function ensureDir(dir: string): void {
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
  }
}

function contentAlreadyExists(dateStr: string): {
  json: boolean;
  md: boolean;
} {
  const jsonPath = path.join(CONTENT_DIR, `${dateStr}.json`);
  const mdPath = path.join(CONTENT_DIR, `${dateStr}.md`);
  return {
    json: fs.existsSync(jsonPath),
    md: fs.existsSync(mdPath),
  };
}

// ─── OpenAI Client ───────────────────────────────────────────────────────────

const openai = new OpenAI({
  apiKey: process.env.OPENAI_API_KEY,
});

async function generate(systemPrompt: string, userPrompt: string): Promise<string> {
  const response = await openai.chat.completions.create({
    model: MODEL,
    messages: [
      { role: "system", content: systemPrompt },
      { role: "user", content: userPrompt },
    ],
    temperature: 0.85,
    max_tokens: 600,
  });
  return (response.choices[0].message.content ?? "").trim();
}

// Checks if the OpenAI API is available (quota not exceeded)
async function checkApiAvailability(): Promise<boolean> {
  try {
    await openai.chat.completions.create({
      model: "gpt-4o-mini",
      messages: [{ role: "user", content: "ping" }],
      max_tokens: 1,
    });
    return true;
  } catch (err: unknown) {
    if (err instanceof Error && err.message.includes("insufficient_quota")) {
      return false;
    }
    return false;
  }
}

// ─── Content Generators ──────────────────────────────────────────────────────

async function generateDailyPrayer(dateStr: string): Promise<string> {
  console.log("  📿  Generating Daily Prayer...");
  const system = `You are a devout, Spirit-filled minister writing a short daily prayer for a Christian devotional platform. 
The prayer should be heartfelt, biblically grounded, and suitable for all believers. 
Keep it concise (4–6 sentences), warm, and uplifting. 
Do not include a title — just the prayer text itself.`;
  const user = `Write a short daily prayer for ${dateStr}. 
The prayer should focus on a relevant spiritual theme for the day (e.g., faith, strength, gratitude, guidance, peace, or love).
End with "Amen."`;
  return generate(system, user);
}

async function generateWordOfTheDay(dateStr: string): Promise<{
  word: string;
  language: string;
  transliteration: string;
  meaning: string;
  verse: string;
  reflection: string;
}> {
  console.log("  📖  Generating Word of the Day (Greek/Hebrew)...");
  const system = `You are a biblical scholar and theologian. 
You provide insightful, accurate explanations of Greek (New Testament) and Hebrew (Old Testament) words for a Christian devotional platform.
Alternate between Greek and Hebrew words. Today's date is ${dateStr}.
Respond ONLY with a valid JSON object — no markdown fences, no extra text.`;
  const user = `Provide a meaningful Greek or Hebrew word of the day for ${dateStr}.
Return a JSON object with these exact keys:
{
  "word": "<original script, e.g. ἀγάπη or שָׁלוֹם>",
  "language": "<Greek or Hebrew>",
  "transliteration": "<romanized pronunciation>",
  "meaning": "<concise English meaning, 1–2 sentences>",
  "verse": "<a relevant Bible verse reference and short quote>",
  "reflection": "<a 2–3 sentence devotional reflection connecting the word to daily life>"
}`;
  const raw = await generate(system, user);
  // Strip any accidental markdown fences
  const cleaned = raw.replace(/^```[a-z]*\n?/i, "").replace(/\n?```$/i, "").trim();
  return JSON.parse(cleaned);
}

async function generateShortSermon(dateStr: string): Promise<{
  title: string;
  scripture: string;
  body: string;
}> {
  console.log("  🎤  Generating Weekly Short Sermon (Sunday)...");
  const system = `You are Rev Fab fire, a Spirit-filled, biblically grounded preacher writing a short Sunday sermon for a Christian devotional platform.
Your sermons are inspiring, practical, and rooted in Scripture.
The sermon should be concise but impactful — suitable for a brief Sunday reading.`;
  const user = `Write a short Sunday sermon for ${dateStr}.
Return a JSON object with these exact keys (no markdown fences):
{
  "title": "<sermon title>",
  "scripture": "<main Scripture reference and short quote>",
  "body": "<the sermon body — 3 to 4 short paragraphs, each 3–5 sentences, covering: introduction/hook, exposition of Scripture, application to daily life, and a closing call to action or prayer prompt>"
}`;
  const raw = await generate(system, user);
  const cleaned = raw.replace(/^```[a-z]*\n?/i, "").replace(/\n?```$/i, "").trim();
  return JSON.parse(cleaned);
}

// ─── Main ─────────────────────────────────────────────────────────────────────

async function main() {
  const dateStr = getTodayISO();
  const sunday = isSunday();

  console.log("\n╔══════════════════════════════════════════════════════╗");
  console.log(`║   Spirit Series Platform — Daily Content Generator   ║`);
  console.log("╚══════════════════════════════════════════════════════╝");
  console.log(`\n  Date  : ${dateStr}`);
  console.log(`  Day   : ${new Date().toLocaleDateString("en-US", { weekday: "long" })}`);
  console.log(`  Sunday: ${sunday ? "Yes — Short Sermon will be generated" : "No — skipping Short Sermon"}\n`);

  ensureDir(CONTENT_DIR);

  const existing = contentAlreadyExists(dateStr);
  if (existing.json && existing.md) {
    console.log(`  ✅  Content for ${dateStr} already exists. Nothing to do.\n`);
    const existingContent = JSON.parse(
      fs.readFileSync(path.join(CONTENT_DIR, `${dateStr}.json`), "utf-8")
    );
    console.log("  Existing content summary:");
    console.log(`    • Daily Prayer   : ${existingContent.dailyPrayer?.slice(0, 60)}...`);
    console.log(`    • Word of the Day: ${existingContent.wordOfTheDay?.word} (${existingContent.wordOfTheDay?.language})`);
    if (existingContent.shortSermon) {
      console.log(`    • Short Sermon   : "${existingContent.shortSermon?.title}"`);
    }
    console.log();
    return;
  }

  // ── Generate content ──────────────────────────────────────────────────────
  let dailyPrayer: string;
  let wordOfTheDay: Awaited<ReturnType<typeof generateWordOfTheDay>>;
  let shortSermon: Awaited<ReturnType<typeof generateShortSermon>> | null = null;

  try {
    dailyPrayer = await generateDailyPrayer(dateStr);
  } catch (err) {
    console.error("  ❌  Failed to generate Daily Prayer:", err);
    process.exit(1);
  }

  try {
    wordOfTheDay = await generateWordOfTheDay(dateStr);
  } catch (err) {
    console.error("  ❌  Failed to generate Word of the Day:", err);
    process.exit(1);
  }

  if (sunday) {
    try {
      shortSermon = await generateShortSermon(dateStr);
    } catch (err) {
      console.error("  ❌  Failed to generate Short Sermon:", err);
      process.exit(1);
    }
  }

  // ── Build output object ───────────────────────────────────────────────────
  const output: Record<string, unknown> = {
    date: dateStr,
    generatedAt: new Date().toISOString(),
    author: AUTHOR,
    dailyPrayer,
    wordOfTheDay,
  };
  if (shortSermon) {
    output.shortSermon = shortSermon;
  }

  // ── Save JSON ─────────────────────────────────────────────────────────────
  const jsonPath = path.join(CONTENT_DIR, `${dateStr}.json`);
  fs.writeFileSync(jsonPath, JSON.stringify(output, null, 2), "utf-8");
  console.log(`\n  💾  Saved JSON  → ${jsonPath}`);

  // ── Save Markdown ─────────────────────────────────────────────────────────
  const dayLabel = new Date().toLocaleDateString("en-US", {
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
  });

  let md = `# Spirit Series — Daily Content\n\n`;
  md += `**Date:** ${dayLabel}  \n`;
  md += `**Author:** ${AUTHOR}  \n\n`;
  md += `---\n\n`;

  // Daily Prayer
  md += `## 🙏 Daily Prayer\n\n`;
  md += `> ${dailyPrayer.split("\n").join("\n> ")}\n\n`;
  md += `*— ${AUTHOR}*\n\n`;
  md += `---\n\n`;

  // Word of the Day
  md += `## 📖 Word of the Day\n\n`;
  md += `**Word:** ${wordOfTheDay.word} *(${wordOfTheDay.language})*  \n`;
  md += `**Transliteration:** ${wordOfTheDay.transliteration}  \n`;
  md += `**Meaning:** ${wordOfTheDay.meaning}  \n\n`;
  md += `**Scripture:** *${wordOfTheDay.verse}*  \n\n`;
  md += `**Reflection:** ${wordOfTheDay.reflection}  \n\n`;
  md += `*— ${AUTHOR}*\n\n`;
  md += `---\n\n`;

  // Short Sermon (Sundays only)
  if (shortSermon) {
    md += `## 🎤 Short Sermon of the Week\n\n`;
    md += `### ${shortSermon.title}\n\n`;
    md += `**Scripture:** *${shortSermon.scripture}*\n\n`;
    md += shortSermon.body
      .split("\n")
      .filter((l) => l.trim())
      .join("\n\n");
    md += `\n\n*— ${AUTHOR}*\n\n`;
    md += `---\n\n`;
  }

  md += `*Generated automatically by the Spirit Series Platform content engine.*\n`;

  const mdPath = path.join(CONTENT_DIR, `${dateStr}.md`);
  fs.writeFileSync(mdPath, md, "utf-8");
  console.log(`  💾  Saved Markdown → ${mdPath}`);

  // ── Summary ───────────────────────────────────────────────────────────────
  console.log("\n  ✅  Content generation complete!\n");
  console.log("  Summary:");
  console.log(`    • Daily Prayer   : ${dailyPrayer.slice(0, 80)}...`);
  console.log(`    • Word of the Day: ${wordOfTheDay.word} (${wordOfTheDay.language}) — "${wordOfTheDay.transliteration}" = ${wordOfTheDay.meaning.slice(0, 50)}...`);
  if (shortSermon) {
    console.log(`    • Short Sermon   : "${shortSermon.title}"`);
  } else {
    console.log(`    • Short Sermon   : Not generated (not Sunday)`);
  }
  console.log();
}

main().catch((err) => {
  console.error("\n  ❌  Unhandled error:", err);
  process.exit(1);
});
