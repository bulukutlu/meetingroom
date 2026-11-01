# Tile biasing unit (ITS3 TDR-021 §3, MOSS paper JINST 18 C01044)

**Where:** one biasing block per tile, on the *top* edge of the pixel array. Size 3.571 × 0.060 mm, 12 per RSU, 0.61 % of RSU area (TDR Table 3.4).

**What it does:** 8-bit static DACs local to the tile generate the bias currents and voltages for the analogue front-ends. Includes the single, common discriminator threshold (VCASB etc.) applied to every pixel in the tile. Per-pixel tuning is only via charge-injection + threshold scans, not per-pixel DACs.

**Calibration/monitoring:** buffered DAC outputs and voltages derived from the supply rails go to ADCs in the left end cap, over wires running the full sensor length, shared by all tiles.

**Control from the stitched backbone:** the backbone carries slow control (serial, multi-drop, RSU addressing, Fig. 5 of MOSS paper) from the left end cap to each RSU/tile; the tile's slow-control registers set the DAC codes. Data return on the separate point-to-point 160 Mbit/s link.

**Power:** the backbone has its own supply; each tile has power switches, so a faulty tile can be switched off.

**Yield:** MOSS has 80 DACs per chip, no significant yield loss seen in bias generation/DACs (TDR Fig. 3.29).

*Caveat: the slow-control-to-DAC step is inferred from the architecture text; neither document details the register map.*
