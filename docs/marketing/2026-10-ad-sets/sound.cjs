// Builds each set's soundtrack with ElevenLabs: voiceover lines, sound effects and a
// music bed from the "audio" block in sets/<set>.json, mixed to <root>/<set>/mix.wav
// with the music ducked under the voice. Clips are cached by their request, so a
// re-run only pays for what changed.
//
//   ELEVENLABS_API_KEY=... node docs/marketing/2026-10-ad-sets/sound.cjs --root build/ad-sets [--sets a,b,c]
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

const arg = (name, fallback) => { const i = process.argv.indexOf(name); return i > 0 ? process.argv[i + 1] : fallback; };
const root = path.resolve(arg('--root', 'build/ad-sets'));
const sets = arg('--sets', 'a,b,c').split(',');
const key = process.env.ELEVENLABS_API_KEY;
if (!key) throw new Error('Set ELEVENLABS_API_KEY');
const cache = path.join(root, 'audio-cache');
fs.mkdirSync(cache, { recursive: true });
const API = 'https://api.elevenlabs.io/v1';

async function clip(kind, url, body) {
  const file = path.join(cache, `${kind}-${crypto.createHash('sha1').update(url + JSON.stringify(body)).digest('hex').slice(0, 16)}.mp3`);
  if (fs.existsSync(file)) return file;
  for (let attempt = 1; ; attempt++) {
    const res = await fetch(url, { method: 'POST', headers: { 'xi-api-key': key, 'content-type': 'application/json', accept: 'audio/mpeg' }, body: JSON.stringify(body) });
    if (res.ok) { fs.writeFileSync(file, Buffer.from(await res.arrayBuffer())); console.log(`  made ${kind}: ${body.text || body.prompt}`.slice(0, 110)); return file; }
    const text = await res.text();
    if (attempt >= 3 || res.status < 500 && res.status !== 429) throw new Error(`${kind} ${res.status}: ${text.slice(0, 300)}`);
    await new Promise((r) => setTimeout(r, 2000 * attempt));
  }
}

const seconds = (file) => Number(spawnSync('ffprobe', ['-v', 'error', '-show_entries', 'format=duration', '-of', 'csv=p=0', file], { encoding: 'utf8' }).stdout);

// Trims the silence around a voice take, shortens every pause inside it to `max` seconds
// (eleven_v3 pauses long between phrases and has no speed setting) and levels it, so
// every line sits at the same loudness.
function tighten(file, max) {
  const out = file.replace(/\.(mp3|wav)$/, `-tight${max}-level.wav`);
  if (fs.existsSync(out)) return out;
  const cut = `silenceremove=start_periods=1:start_threshold=-45dB:stop_periods=-1:stop_duration=${max}:stop_threshold=-45dB:stop_silence=${max}`;
  const r = spawnSync('ffmpeg', ['-y', '-loglevel', 'error', '-i', file, '-af', `${cut},loudnorm=I=-18:LRA=7:TP=-2,aresample=44100,apad=pad_dur=0.05`, out], { encoding: 'utf8', windowsHide: true });
  if (r.status !== 0) throw new Error(r.stderr);
  return out;
}

// Reads every line in one take, so the voice and mood hold across the script, then cuts
// the take into one file per line by its character timings.
async function oneTake(audio, lines, settings) {
  let text = '';
  const spans = lines.map((line) => {
    if (text) text += '\n\n';
    const spoken = line.text.replace(/^\[[^\]]*\]\s*/, '');
    const from = text.length + line.text.length - spoken.length;
    text += line.text;
    return [from, text.length - 1];
  });
  const body = { text, ...settings };
  const url = `${API}/text-to-speech/${audio.voice}/with-timestamps?output_format=mp3_44100_128`;
  const base = path.join(cache, `take-${crypto.createHash('sha1').update(url + JSON.stringify(body)).digest('hex').slice(0, 16)}`);
  if (!fs.existsSync(`${base}.json`)) {
    const res = await fetch(url, { method: 'POST', headers: { 'xi-api-key': key, 'content-type': 'application/json' }, body: JSON.stringify(body) });
    if (!res.ok) throw new Error(`take ${res.status}: ${(await res.text()).slice(0, 300)}`);
    const json = await res.json();
    fs.writeFileSync(`${base}.mp3`, Buffer.from(json.audio_base64, 'base64'));
    fs.writeFileSync(`${base}.json`, JSON.stringify(json.alignment));
    console.log(`  made one take of ${lines.length} lines`);
  }
  const { character_start_times_seconds: starts, character_end_times_seconds: ends } = JSON.parse(fs.readFileSync(`${base}.json`, 'utf8'));
  return spans.map(([from, to], n) => {
    const prevEnd = n ? ends[spans[n - 1][1]] : 0;
    const nextStart = n < spans.length - 1 ? starts[spans[n + 1][0]] : seconds(`${base}.mp3`);
    const a = Math.max(prevEnd, starts[from] - 0.06);
    const b = Math.min(nextStart, ends[to] + 0.15);
    const out = `${base}-${n}.wav`;
    if (!fs.existsSync(out)) {
      const r = spawnSync('ffmpeg', ['-y', '-loglevel', 'error', '-i', `${base}.mp3`, '-af', `atrim=${a.toFixed(3)}:${b.toFixed(3)},asetpts=N/SR/TB,afade=t=in:d=0.02`, out], { encoding: 'utf8', windowsHide: true });
      if (r.status !== 0) throw new Error(r.stderr);
    }
    return out;
  });
}

async function build(s) {
  const spec = JSON.parse(fs.readFileSync(path.join(__dirname, 'sets', `${s}.json`), 'utf8'));
  const audio = spec.audio;
  if (!audio) return console.log(`${s}: no audio block`);
  console.log(`${s}:`);
  const voice = [];
  // eleven_v3 takes [audio tags] in the text and only a stability setting.
  const model = audio.model || 'eleven_multilingual_v2';
  const defaults = model === 'eleven_v3' ? { stability: 0.5 } : { stability: 0.5, similarity_boost: 0.8, style: 0.15, speed: 1.0 };
  const lines = audio.lines || [];
  const takes = audio.oneTake && await oneTake(audio, lines, { model_id: model, voice_settings: { ...defaults, ...audio.voiceSettings }, ...(audio.seed != null && { seed: audio.seed }) });
  for (const [n, line] of lines.entries()) {
    const take = takes ? takes[n] : await clip('vo', `${API}/text-to-speech/${audio.voice}?output_format=mp3_44100_128`,
      { text: line.text, model_id: model, voice_settings: { ...defaults, ...audio.voiceSettings, ...line.settings }, ...(line.seed != null && { seed: line.seed }) });
    const file = audio.maxPause ? tighten(take, audio.maxPause) : take;
    const tempo = line.tempo ?? audio.tempo;
    voice.push({ file, at: line.at, gain: line.gain ?? 0, tempo });
    const end = line.at + seconds(file) / (tempo || 1);
    const next = audio.lines.find((l) => l.at > line.at);
    console.log(`  "${line.text}" ${line.at.toFixed(2)}-${end.toFixed(2)} s${next && end > next.at ? `  OVERLAPS next line at ${next.at}` : ''}${end > spec.duration ? '  RUNS PAST THE END' : ''}`);
  }
  const effects = [];
  for (const fx of audio.sfx || []) {
    const file = await clip('sfx', `${API}/sound-generation`, { text: fx.prompt, duration_seconds: fx.seconds, prompt_influence: fx.influence ?? 0.6, model_id: 'eleven_text_to_sound_v2' });
    for (const at of [].concat(fx.at)) effects.push({ file, at, gain: fx.gain ?? 0 });
  }
  const music = audio.music && await clip('music', `${API}/music`,
    { prompt: audio.music.prompt, music_length_ms: Math.max(10000, Math.ceil(spec.duration * 1000) + 1000), model_id: 'music_v1', force_instrumental: true });

  // One input per clip; delay each to its time, then mix voice, effects and the ducked music bed.
  const inputs = [];
  const graph = [];
  const add = (list, label) => list.map((c) => {
    const i = inputs.push(c.file) - 1;
    const ms = Math.round(c.at * 1000);
    // A short fade at each clip's end, so a generated effect never stops dead. A tempo
    // speeds a line up without changing its pitch.
    const length = seconds(c.file) / (c.tempo || 1);
    const fade = Math.min(0.25, length * 0.3);
    graph.push(`[${i}]aresample=48000,aformat=channel_layouts=stereo,${c.tempo ? `atempo=${c.tempo},` : ''}afade=t=out:st=${(length - fade).toFixed(3)}:d=${fade.toFixed(3)},adelay=${ms}|${ms},volume=${c.gain}dB[${label}${i}]`);
    return `[${label}${i}]`;
  });
  const v = add(voice, 'v');
  const f = add(effects, 'f');
  const buses = [];
  // The voice keys two duckers: the effects dip a little under it, the music more.
  if (v.length) graph.push(`${v.join('')}amix=inputs=${v.length}:normalize=0,asplit=3[vo][key][fxkey]`);
  if (f.length) {
    graph.push(`${f.join('')}amix=inputs=${f.length}:normalize=0[fxall]`);
    if (v.length) graph.push('[fxall][fxkey]sidechaincompress=threshold=0.03:ratio=3:attack=10:release=250[fx]');
    buses.push(v.length ? '[fx]' : '[fxall]');
  } else if (v.length) graph.push('[fxkey]anullsink');
  if (music) {
    const i = inputs.push(music) - 1;
    graph.push(`[${i}]aresample=48000,aformat=channel_layouts=stereo,volume=${audio.music.gain ?? -14}dB,afade=t=out:st=${spec.duration - 1.2}:d=1.2[bed]`);
    if (v.length) { graph.push('[bed][key]sidechaincompress=threshold=0.02:ratio=6:attack=15:release=350[duck]'); buses.push('[duck]'); }
    else buses.push('[bed]');
  }
  if (v.length) { if (!music) graph.push('[key]anullsink'); buses.push('[vo]'); }
  graph.push(`${buses.join('')}amix=inputs=${buses.length}:normalize=0,apad,atrim=0:${spec.duration},loudnorm=I=-14:TP=-1.5:LRA=11,aresample=48000[out]`);
  const out = path.join(root, s, 'mix.wav');
  const r = spawnSync('ffmpeg', ['-y', '-loglevel', 'error', ...inputs.flatMap((p) => ['-i', p]), '-filter_complex', graph.join(';'), '-map', '[out]', '-ar', '48000', out], { encoding: 'utf8', windowsHide: true });
  if (r.status !== 0) throw new Error(r.stderr);
  console.log(`  mix: ${out}`);
}

(async () => { for (const s of sets) await build(s); })().catch((e) => { console.error(e.message); process.exit(1); });
