import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "../../api/client";

/** Voice input state machine (MR 4C).
 *
 *  idle → recording (timer) → transcribing → idle (transcript delivered)
 *                └─ cancel/Escape: discard everything, no request (guardrail 4)
 *
 *  Routes: browser Web Speech first when supported and preferred (live interim
 *  text), MediaRecorder → /api/transcribe otherwise or after a speech failure.
 *  A speech failure NEVER wipes dictated text (guardrail 3). Transcripts are
 *  only inserted into the composer — never auto-sent (guardrail 6). */

export type VoiceState = "idle" | "recording" | "transcribing";

const MAX_SECONDS = 120;

const PREPARING_COPY =
  "Voice model is being prepared. This can take a few minutes the first time.";
const FAILURE_COPY = "Could not transcribe audio. Try again or type your message.";

type SpeechRecognitionLike = {
  continuous: boolean;
  interimResults: boolean;
  onresult: ((e: any) => void) | null;
  onerror: ((e: any) => void) | null;
  onend: (() => void) | null;
  start: () => void;
  stop: () => void;
  abort: () => void;
};

function speechCtor(): (new () => SpeechRecognitionLike) | null {
  const w = window as any;
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export function useVoiceInput({
  onInterim,
  onFinal,
}: {
  /** live partial dictation (browser route) — replaces the previous interim */
  onInterim: (text: string) => void;
  /** accepted text to append to the composer (never auto-sent) */
  onFinal: (text: string) => void;
}) {
  const [state, setState] = useState<VoiceState>("idle");
  const [seconds, setSeconds] = useState(0);
  const [notice, setNotice] = useState<string | null>(null);
  const [preparing, setPreparing] = useState(false);
  // Live level analyser for the waveform — driven by the REAL mic signal.
  const [analyser, setAnalyser] = useState<AnalyserNode | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const vizStreamRef = useRef<MediaStream | null>(null);
  // After a Web Speech failure, later recordings use the server route.
  const speechBrokenRef = useRef(false);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const speechRef = useRef<SpeechRecognitionLike | null>(null);
  const cancelledRef = useRef(false);
  const chunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const { data: status } = useQuery({
    queryKey: ["transcribe-status"],
    queryFn: api.transcribeStatus,
    staleTime: 30_000,
    retry: false,
  });

  const serverState = status?.state ?? "unknown";
  const prefer = status?.prefer ?? "browser_first";
  const speechSupported = typeof window !== "undefined" && speechCtor() !== null;
  // whisper_first NEVER attempts browser speech (guardrail 10).
  const useBrowserRoute =
    prefer === "browser_first" && speechSupported && !speechBrokenRef.current;
  const serverUsable = ["ready", "not_ready", "preparing", "unknown"].includes(serverState);
  const available = useBrowserRoute || serverUsable;

  const tooltip = !available
    ? serverState === "disabled"
      ? "Voice input is not enabled on this instance"
      : FAILURE_COPY
    : serverState === "preparing"
      ? PREPARING_COPY
      : "Voice input";

  function clearTimer() {
    if (timerRef.current) clearInterval(timerRef.current);
    timerRef.current = null;
  }

  const teardown = useCallback(() => {
    clearTimer();
    setSeconds(0);
    recorderRef.current?.stream?.getTracks?.().forEach((t) => t.stop());
    recorderRef.current = null;
    speechRef.current = null;
    chunksRef.current = [];
    vizStreamRef.current?.getTracks?.().forEach((t) => t.stop());
    vizStreamRef.current = null;
    void audioCtxRef.current?.close().catch(() => {});
    audioCtxRef.current = null;
    setAnalyser(null);
  }, []);

  /** Attach a level analyser to a mic stream (best-effort; never breaks
   *  recording — environments without Web Audio just get the fallback dot). */
  function attachAnalyser(stream: MediaStream) {
    try {
      const Ctx =
        (window as unknown as Record<string, unknown>)["AudioContext"] ??
        (window as unknown as Record<string, unknown>)["webkitAudioContext"];
      if (typeof Ctx !== "function") return;
      const ctx = new (Ctx as new () => AudioContext)();
      const source = ctx.createMediaStreamSource(stream);
      const node = ctx.createAnalyser();
      node.fftSize = 512; // 512 time-domain samples → ~25 per bar slice
      source.connect(node);
      audioCtxRef.current = ctx;
      setAnalyser(node);
    } catch {
      /* no visualization — recording still works */
    }
  }

  useEffect(() => () => teardown(), [teardown]);

  function startTimer(onLimit: () => void) {
    const startedAt = Date.now();
    timerRef.current = setInterval(() => {
      const s = Math.floor((Date.now() - startedAt) / 1000);
      setSeconds(s);
      if (s >= MAX_SECONDS) onLimit();
    }, 500);
  }

  async function transcribeBlob(blob: Blob) {
    setState("transcribing");
    // Honest lazy-download copy if the server is still preparing (guardrail 2).
    const slowTimer = setTimeout(() => {
      void api
        .transcribeStatus()
        .then((s) => setPreparing(s.state === "preparing" || s.state === "not_ready"))
        .catch(() => {});
    }, 4000);
    try {
      const result = await api.transcribeAudio(blob);
      if (!cancelledRef.current && result.text) onFinal(result.text);
      if (!cancelledRef.current && !result.text) setNotice("No speech detected in the recording.");
      setState("idle");
    } catch {
      setNotice(FAILURE_COPY); // calm copy, never raw errors (guardrail 12)
      setState("idle");
    } finally {
      clearTimeout(slowTimer);
      setPreparing(false);
      teardown();
    }
  }

  async function startServerRoute() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      attachAnalyser(stream);
      const recorder = new MediaRecorder(stream);
      recorderRef.current = recorder;
      chunksRef.current = [];
      recorder.ondataavailable = (e: BlobEvent) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };
      recorder.onstop = () => {
        clearTimer();
        setSeconds(0);
        if (cancelledRef.current) {
          // Escape/cancel: discard audio entirely — no request (guardrail 4).
          teardown();
          setState("idle");
          return;
        }
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || "audio/webm" });
        void transcribeBlob(blob);
      };
      recorder.start();
      setState("recording");
      startTimer(() => recorder.state !== "inactive" && recorder.stop());
    } catch {
      setNotice("Microphone unavailable. Check browser permissions.");
      setState("idle");
    }
  }

  function startBrowserRoute() {
    const Ctor = speechCtor();
    if (!Ctor) return void startServerRoute();
    const rec = new Ctor();
    speechRef.current = rec;
    rec.continuous = true;
    rec.interimResults = true;
    let finalText = "";
    rec.onresult = (e: any) => {
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const alt = e.results[i][0]?.transcript ?? "";
        if (e.results[i].isFinal) {
          finalText += alt;
          onFinal(alt.trim());
          onInterim("");
        } else {
          interim += alt;
        }
      }
      if (interim) onInterim(interim.trim());
    };
    rec.onerror = () => {
      // Guardrail 3: keep whatever was dictated; don't wipe text. There is no
      // recorded audio on this route, so fall back for FUTURE recordings.
      speechBrokenRef.current = true;
      onInterim("");
      teardown();
      setState("idle");
      setNotice(
        finalText
          ? "Browser dictation stopped — your text was kept. The next recording will use server transcription."
          : "Browser dictation failed. The next recording will use server transcription.",
      );
    };
    rec.onend = () => {
      if (state !== "idle") {
        teardown();
        setState("idle");
      }
    };
    rec.start();
    setState("recording");
    startTimer(() => rec.stop());
    // Web Speech exposes no stream — open one purely for the level meter so
    // the user still sees they're being heard (best-effort).
    void navigator.mediaDevices
      ?.getUserMedia?.({ audio: true })
      .then((stream) => {
        vizStreamRef.current = stream;
        attachAnalyser(stream);
      })
      .catch(() => {});
  }

  function start() {
    if (state !== "idle" || !available) return;
    setNotice(null);
    cancelledRef.current = false;
    if (useBrowserRoute) startBrowserRoute();
    else void startServerRoute();
  }

  /** Stop = finish and transcribe (guardrail 5). */
  function stop() {
    if (state !== "recording") return;
    if (speechRef.current) {
      speechRef.current.stop();
      teardown();
      setState("idle"); // browser route delivered text live; nothing to transcribe
    } else if (recorderRef.current && recorderRef.current.state !== "inactive") {
      recorderRef.current.stop();
    }
  }

  /** Cancel/Escape = discard everything (guardrails 4-5). */
  function cancel() {
    if (state !== "recording") return;
    cancelledRef.current = true;
    if (speechRef.current) {
      speechRef.current.abort();
      onInterim(""); // interim text was never accepted — clear it
    }
    if (recorderRef.current && recorderRef.current.state !== "inactive") {
      recorderRef.current.stop(); // onstop sees cancelledRef and discards
    } else {
      teardown();
      setState("idle");
    }
    clearTimer();
    setSeconds(0);
    setNotice(null);
    setState("idle");
  }

  return {
    state,
    seconds,
    notice,
    preparing,
    available,
    tooltip,
    serverState,
    analyser,
    start,
    stop,
    cancel,
    dismissNotice: () => setNotice(null),
  };
}
