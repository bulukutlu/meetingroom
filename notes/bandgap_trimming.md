# Bandgap reference and trimming

## Not quite temperature compensation
The bandgap's **job** is to give a voltage (about 1.2 V) that does not move with temperature or supply. It does that by itself, by design. **Trimming** is a separate step: it corrects the *chip-to-chip* offset of that voltage caused by fabrication spread.

## How a bandgap works
- A diode/BJT voltage **V_BE falls** with temperature, about -2 mV/K (CTAT).
- The difference of two V_BE at different current densities, **ΔV_BE = (kT/q)·ln N, rises** with temperature (PTAT).
- Sum them: **V_BGR = V_BE + α·ΔV_BE**. Choose α so the slopes cancel. Result is about 1.2 V (silicon bandgap), flat around room temperature.

## Why trimming is needed
- Resistor ratios, BJT/diode area ratios and amplifier offset vary from chip to chip (process mismatch).
- V_BGR then lands a few mV off, and the temperature slope is slightly off too.
- Every bias DAC is scaled from V_BGR, so this error moves all currents and thresholds by the same factor. Front-end gain, threshold and noise would then differ from tile to tile.

## How it is done (generic, standard practice)
1. Measure V_BGR on the chip (here via the monitoring ADCs in the end cap).
2. Adjust a small **trim DAC / switchable resistor bank** that sets the PTAT gain α (or the output divider).
3. Store the code in a **slow-control register** (or fuses/OTP) and reload after power-up.
4. Iterate until V_BGR hits target; trimming the PTAT term also flattens the slope.

## On ITS3 / MOSS (what the documents say)
- MOSS has a bandgap + temperature sensor block, and **80 DACs** per chip (TDR Table 3.1, §3).
- TDR Fig. 3.29 shows the V_BGR distribution over MOSS chips **before any tuning**: spread of order **0.25 mV** per wafer (σ read from the plot labels), within spec.
- Tile DACs and the V_BGR/DAC outputs are monitored via the end-cap ADCs.

*Caveat: neither the TDR nor the MOSS paper describes the trim circuit or register. The "how it is done" part is the generic method, not ITS3 specifics.*
