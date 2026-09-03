import { useEffect, useRef } from "react";

/** Live level bars driven by the actual microphone signal — the user can SEE
 *  they are being heard. Bars are per-slice RMS amplitude of the time-domain
 *  waveform (the frequency spectrum left most of the strip flat for voice),
 *  with asymmetric exponential smoothing: quick rise, gentle fall — no snap.
 *  Falls back to a pulsing dot when no analyser is available (never fake). */
export function VoiceWaveform({
  analyser,
  wide = false,
}: {
  analyser: AnalyserNode | null;
  wide?: boolean;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const BARS = wide ? 44 : 20;

  useEffect(() => {
    if (!analyser || !canvasRef.current) return;
    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const data = new Uint8Array(analyser.fftSize);
    const levels = new Float32Array(BARS); // smoothed state across frames
    let raf = 0;

    function draw() {
      if (!ctx) return;
      analyser!.getByteTimeDomainData(data);
      const w = canvas.width;
      const h = canvas.height;
      ctx.clearRect(0, 0, w, h);
      const step = w / BARS;
      const bucket = Math.max(Math.floor(data.length / BARS), 1);
      for (let i = 0; i < BARS; i++) {
        let sumSquares = 0;
        for (let j = 0; j < bucket; j++) {
          const v = ((data[i * bucket + j] ?? 128) - 128) / 128; // -1..1
          sumSquares += v * v;
        }
        const target = Math.min(1, Math.sqrt(sumSquares / bucket) * 2.8);
        // Attack fast (0.45 toward louder), release slow (0.12 toward quieter).
        const alpha = target > levels[i] ? 0.45 : 0.12;
        levels[i] += (target - levels[i]) * alpha;
        const barH = Math.max(2, levels[i] * h);
        const x = i * step + step * 0.25;
        ctx.fillStyle = "rgba(220, 60, 60, 0.9)";
        ctx.beginPath();
        ctx.roundRect(x, (h - barH) / 2, step * 0.5, barH, 2);
        ctx.fill();
      }
      raf = requestAnimationFrame(draw);
    }
    raf = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(raf);
  }, [analyser, BARS]);

  if (!analyser) {
    // Honest fallback: a pulsing dot (recording is on, levels unavailable).
    return <span className="size-2 animate-pulse rounded-full bg-destructive" aria-hidden />;
  }
  return wide ? (
    <canvas ref={canvasRef} width={620} height={48} className="h-12 w-full" aria-hidden />
  ) : (
    <canvas ref={canvasRef} width={96} height={22} className="h-[22px] w-24" aria-hidden />
  );
}
