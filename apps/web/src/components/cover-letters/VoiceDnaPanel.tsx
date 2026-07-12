/** Voice DNA panel (wireframe cl08/cl09): tone + formality range sliders. */
import { formalityLabel, toneLabel } from "./insights";

export function VoiceDnaPanel({
  tone,
  formality,
  onToneChange,
  onFormalityChange,
}: {
  tone: number;
  formality: number;
  onToneChange: (value: number) => void;
  onFormalityChange: (value: number) => void;
}) {
  return (
    <section className="glass rounded-2xl border border-white/10 p-5" data-testid="voice-dna-panel">
      <div className="mb-4 flex items-center gap-2">
        <i className="fa-solid fa-sliders text-sm text-aether-violet" aria-hidden="true" />
        <h2 className="text-sm font-semibold">Voice DNA</h2>
      </div>
      <div className="mb-4">
        <div className="mb-1.5 flex items-center justify-between">
          <span className="text-[11px] text-aether-muted" id="tone-slider-label">
            Tone
          </span>
          <span className="mono text-[11px] text-aether-violet" data-testid="tone-label">
            {toneLabel(tone)}
          </span>
        </div>
        <input
          type="range"
          min={0}
          max={100}
          value={tone}
          onChange={(e) => onToneChange(Number(e.target.value))}
          className="h-11 w-full accent-aether-coral"
          aria-labelledby="tone-slider-label"
          aria-valuetext={toneLabel(tone)}
          data-testid="tone-slider"
        />
      </div>
      <div>
        <div className="mb-1.5 flex items-center justify-between">
          <span className="text-[11px] text-aether-muted" id="formality-slider-label">
            Formality
          </span>
          <span className="mono text-[11px] text-aether-violet" data-testid="formality-label">
            {formalityLabel(formality)}
          </span>
        </div>
        <input
          type="range"
          min={0}
          max={100}
          value={formality}
          onChange={(e) => onFormalityChange(Number(e.target.value))}
          className="h-11 w-full accent-aether-coral"
          aria-labelledby="formality-slider-label"
          aria-valuetext={formalityLabel(formality)}
          data-testid="formality-slider"
        />
      </div>
      <p className="mt-2 text-[10px] text-aether-muted-dim">
        Sliders steer the next Regenerate / Request Changes draft.
      </p>
    </section>
  );
}
