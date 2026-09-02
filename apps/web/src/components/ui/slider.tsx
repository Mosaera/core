import { Slider as SliderPrimitive } from "@base-ui/react/slider";

import { cn } from "@/lib/utils";

/** Themed single-value slider (base-ui), matching the app's ui/ wrappers. */
export function Slider({
  value,
  onValueChange,
  min = 0,
  max = 100,
  step = 1,
  className,
  "aria-label": ariaLabel,
}: {
  value: number;
  onValueChange: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
  className?: string;
  "aria-label"?: string;
}) {
  return (
    <SliderPrimitive.Root
      value={value}
      onValueChange={(v) => onValueChange(Array.isArray(v) ? v[0] : (v as number))}
      min={min}
      max={max}
      step={step}
      className={cn("flex w-full touch-none items-center select-none", className)}
    >
      <SliderPrimitive.Control className="flex w-full items-center py-1.5">
        <SliderPrimitive.Track className="h-1.5 w-full rounded-full bg-foreground/15">
          <SliderPrimitive.Indicator className="rounded-full bg-primary" />
          <SliderPrimitive.Thumb
            aria-label={ariaLabel}
            className="size-4 rounded-full bg-primary ring-2 ring-background outline-none focus-visible:ring-2 focus-visible:ring-ring"
          />
        </SliderPrimitive.Track>
      </SliderPrimitive.Control>
    </SliderPrimitive.Root>
  );
}
