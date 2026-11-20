// The fixed construction every actuator shares, in 3D: mfcad's build_matrix
// with proven_geom / proven_bore (the matrices printed and tested on the rig).
// World frame: z = 0 is membrane 1. Bottom plate z in [-bottom_t, 0] (chambers
// open upward at z = 0); middle plate z in [0, mid_t] (valve seats on its
// underside); top plate z in [mid_t, mid_t + top_t].

export const PROUD = 0.5;   // how far a cut reaches past the face it opens on

export const STACK = Object.freeze({
  d: 1.8, seat_gap: 3.2, col: 6.0, pocket_d: 2.4, relief_depth: 0.54,
  chamber_l: 3.8, chamber_w: 7.0, chamber_depth: 1.35, chamber_dy: 1.6,
  bend: 1.35, wall: 1.2, floor: 1.0, edge_wall: 1.5,
  ctrl_z: 3.25, level1: 3.0, level2: 5.8, mid_t: 8.0, top_t: 3.0, top_t_vacuum: 1.2,
  bottom_t_min: 7.7, nut_depth: 2.5,
  bore_d: 1.8, lead: 0.6, lead_len: 0.3 / Math.tan(5.0 * Math.PI / 180),
  needle_stop: 1.2, neck_len: 1.0, corner_key: 3.0,
  bleed_w: 0.8, bleed_d: 0.4, bleeds: 3,
  get r() { return this.d / 2; },
  get port_r() { return (this.bore_d + this.lead) / 2; },
  get level_step() { return this.d + this.floor; },
  level_z(k) { return this.ctrl_z + k * this.level_step; },
  bottom_t(levels) {
    const t = Math.max(this.bottom_t_min, this.level_z(levels - 1) + this.port_r + this.floor);
    return Math.ceil(t * 10 - 1e-6) / 10;
  },
  middle_t(actuation = 'pressure', bowlDepth = 0) {
    if (actuation !== 'vacuum') return this.mid_t;
    const t = this.level2 + this.r + this.floor + bowlDepth;
    return Math.max(this.mid_t, Math.ceil(t * 10 - 1e-6) / 10);
  },
  top_thickness(actuation = 'pressure') { return actuation === 'vacuum' ? this.top_t_vacuum : this.top_t; },
  nut_level(k, levels, radius) {
    const topOfNut = this.bottom_t(levels) - this.nut_depth;
    return this.level_z(k) + radius + this.floor > topOfNut + 1e-9;
  },
});
