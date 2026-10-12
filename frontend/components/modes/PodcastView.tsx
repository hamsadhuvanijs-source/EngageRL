"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { useTelemetry } from "@/components/telemetry/TelemetryProvider";
import type { PodcastContent } from "@/types/api";

// Browsers don't expose a reliable "gender" field on SpeechSynthesisVoice, but most voice
// names hint at it (Windows: "Microsoft Zira", "Microsoft David"; Chrome: "Google UK English
// Female"; macOS: "Samantha", "Alex"; etc). Matching against the gender Gemini tagged each host
// with (see backend PodcastGenerator's prompt) is far more reliable than picking voices in
// list order, which is what previously made a host named "Maya" sound like a man.
const FEMALE_VOICE_HINTS = [
  "female", "woman", "zira", "hazel", "susan", "samantha", "victoria", "karen", "moira", "tessa",
  "fiona", "kate", "serena", "allison", "ava", "aria", "jenny", "sonia", "libby", "olivia", "emma",
  "eva", "amy", "salli", "joanna", "kimberly", "kendra", "linda", "catherine", "michelle",
];
const MALE_VOICE_HINTS = [
  "male", "man", "david", "mark", "daniel", "fred", "george", "james", "alex", "ryan", "guy",
  "eric", "brian", "tom", "oliver", "christopher", "matthew", "andrew", "justin", "kevin", "sean",
  "will", "arthur",
];

// Slight pitch/rate offset per host on top of the matched voice, so the two hosts stay audibly
// distinct even on a browser/OS that only exposes one usable voice per matched gender.
const HOST_VOICE_STYLE: { pitch: number; rate: number }[] = [
  { pitch: 1, rate: 1 },
  { pitch: 1.08, rate: 0.97 },
];

// Chrome silently stops long-running speechSynthesis playback after ~15s unless nudged — this
// pause/resume ping is the standard workaround, harmless on browsers that don't need it.
const RESUME_NUDGE_MS = 10000;

function scoreVoiceForGender(voice: SpeechSynthesisVoice, gender: "female" | "male"): number {
  const name = voice.name.toLowerCase();
  const hints = gender === "female" ? FEMALE_VOICE_HINTS : MALE_VOICE_HINTS;
  return hints.some((hint) => name.includes(hint)) ? 1 : 0;
}

function pickVoices(genders: ("female" | "male")[]): (SpeechSynthesisVoice | null)[] {
  if (typeof window === "undefined" || !window.speechSynthesis) return genders.map(() => null);
  const all = window.speechSynthesis.getVoices();
  const english = all.filter((v) => v.lang.toLowerCase().startsWith("en"));
  const pool = english.length > 0 ? english : all;
  if (pool.length === 0) return genders.map(() => null);

  const used = new Set<string>();
  return genders.map((gender) => {
    const candidates = pool.filter((v) => !used.has(v.name));
    const matched = candidates.find((v) => scoreVoiceForGender(v, gender) === 1);
    const chosen = matched ?? candidates[0] ?? pool[0];
    if (chosen) used.add(chosen.name);
    return chosen ?? null;
  });
}

type PlaybackStatus = "idle" | "playing" | "paused" | "done";

const HOST_COLOR_VARS = ["var(--accent)", "var(--accent-2)"];

export function PodcastView({ content }: { content: PodcastContent }) {
  const { reportProgress } = useTelemetry();
  const [supported, setSupported] = useState(true);
  const [status, setStatus] = useState<PlaybackStatus>("idle");
  const [currentIndex, setCurrentIndex] = useState(-1);
  const [transcriptOpen, setTranscriptOpen] = useState(false);
  const voicesRef = useRef<(SpeechSynthesisVoice | null)[]>([null, null]);
  const cancelledRef = useRef(false);
  const nudgeIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const lineRefs = useRef<(HTMLDivElement | null)[]>([]);

  const hostIndexOf = useMemo(() => {
    return (speaker: string) => {
      const idx = content.hosts.findIndex((h) => h.name === speaker);
      return idx === -1 ? 0 : idx;
    };
  }, [content.hosts]);

  useEffect(() => {
    if (typeof window === "undefined" || !window.speechSynthesis) {
      setSupported(false);
      return;
    }
    const genders = content.hosts.map((h) => h.gender);
    const loadVoices = () => {
      voicesRef.current = pickVoices(genders);
    };
    loadVoices();
    window.speechSynthesis.onvoiceschanged = loadVoices;
    return () => {
      cancelledRef.current = true;
      window.speechSynthesis.cancel();
      if (nudgeIntervalRef.current) clearInterval(nudgeIntervalRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!transcriptOpen || currentIndex < 0) return;
    lineRefs.current[currentIndex]?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [currentIndex, transcriptOpen]);

  const speakFrom = (startIndex: number) => {
    if (!supported) return;
    cancelledRef.current = false;
    window.speechSynthesis.cancel();
    setStatus("playing");

    const speakSegment = (i: number) => {
      if (cancelledRef.current) return;
      if (i >= content.segments.length) {
        setStatus("done");
        setCurrentIndex(-1);
        reportProgress(1);
        if (nudgeIntervalRef.current) clearInterval(nudgeIntervalRef.current);
        return;
      }
      const segment = content.segments[i];
      setCurrentIndex(i);
      reportProgress(i / content.segments.length);

      const utterance = new SpeechSynthesisUtterance(segment.text);
      const hostIdx = hostIndexOf(segment.speaker);
      const voice = voicesRef.current[hostIdx];
      if (voice) utterance.voice = voice;
      const style = HOST_VOICE_STYLE[hostIdx] ?? HOST_VOICE_STYLE[0];
      utterance.pitch = style.pitch;
      utterance.rate = style.rate;
      utterance.onend = () => speakSegment(i + 1);
      utterance.onerror = () => speakSegment(i + 1);
      window.speechSynthesis.speak(utterance);
    };

    if (nudgeIntervalRef.current) clearInterval(nudgeIntervalRef.current);
    nudgeIntervalRef.current = setInterval(() => {
      if (window.speechSynthesis.speaking && !window.speechSynthesis.paused) {
        window.speechSynthesis.pause();
        window.speechSynthesis.resume();
      }
    }, RESUME_NUDGE_MS);

    speakSegment(startIndex);
  };

  const onPlay = () => speakFrom(currentIndex >= 0 ? currentIndex : 0);

  const onPause = () => {
    window.speechSynthesis.pause();
    setStatus("paused");
  };

  const onResume = () => {
    window.speechSynthesis.resume();
    setStatus("playing");
  };

  const onStop = () => {
    cancelledRef.current = true;
    window.speechSynthesis.cancel();
    if (nudgeIntervalRef.current) clearInterval(nudgeIntervalRef.current);
    setStatus("idle");
    setCurrentIndex(-1);
  };

  const activeHostIndex = currentIndex >= 0 ? hostIndexOf(content.segments[currentIndex].speaker) : -1;
  const currentSegment = currentIndex >= 0 ? content.segments[currentIndex] : null;

  return (
    <>
      <h1>🎙️ {content.title || "Podcast"}</h1>

      {!supported && (
        <div className="comic-error-banner">
          Your browser doesn&apos;t support spoken playback (Web Speech API) — read the transcript below instead.
        </div>
      )}

      <div className="podcast-player">
        <div className="podcast-hosts">
          {content.hosts.map((host, i) => (
            <div
              key={host.name}
              className={`podcast-host-badge ${activeHostIndex === i ? "podcast-host-active" : ""}`}
              style={{ ["--host-color" as string]: HOST_COLOR_VARS[i % HOST_COLOR_VARS.length] }}
            >
              <div className="podcast-host-avatar">{host.name.charAt(0).toUpperCase()}</div>
              <div className="podcast-host-name">{host.name}</div>
              <div className={`podcast-waveform ${activeHostIndex === i && status === "playing" ? "playing" : ""}`}>
                <span />
                <span />
                <span />
                <span />
                <span />
              </div>
            </div>
          ))}
        </div>

        <div className="podcast-caption">
          {currentSegment ? (
            <>
              <span className="podcast-caption-speaker">{currentSegment.speaker}</span>
              <p className="podcast-caption-text" key={currentIndex}>
                {currentSegment.text}
              </p>
            </>
          ) : (
            <p className="podcast-caption-placeholder">
              {status === "done" ? "Episode finished." : "Press play to start the episode."}
            </p>
          )}
        </div>

        {supported && (
          <div className="podcast-controls">
            {status === "playing" ? (
              <button className="btn" onClick={onPause}>
                ⏸ Pause
              </button>
            ) : status === "paused" ? (
              <button className="btn" onClick={onResume}>
                ▶ Resume
              </button>
            ) : (
              <button className="btn" onClick={onPlay}>
                ▶ {status === "done" ? "Play again" : "Play episode"}
              </button>
            )}
            <button className="btn-secondary" onClick={onStop} disabled={status === "idle"}>
              ■ Stop
            </button>
          </div>
        )}
      </div>

      <details className="podcast-transcript-toggle" onToggle={(e) => setTranscriptOpen(e.currentTarget.open)}>
        <summary>Show full transcript</summary>
        <div className="podcast-transcript">
          {content.segments.map((segment, i) => (
            <div
              key={i}
              ref={(el) => {
                lineRefs.current[i] = el;
              }}
              className={`podcast-line ${hostIndexOf(segment.speaker) === 0 ? "podcast-line-a" : "podcast-line-b"} ${
                i === currentIndex ? "podcast-line-active" : ""
              }`}
              onClick={() => supported && speakFrom(i)}
            >
              <span className="podcast-speaker">{segment.speaker}</span>
              <p>{segment.text}</p>
            </div>
          ))}
        </div>
      </details>
    </>
  );
}
