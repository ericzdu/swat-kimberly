export interface NavLeaf { label: string; file?: string; special?: 'run' | 'dashboard'; }
export interface NavSection { id: string; label: string; icon: string; leaves: NavLeaf[]; defaultOpen?: boolean; }

// Navigation mirrors the SWAT+ Editor "Edit SWAT+ Inputs" panel. Per the SWAT+ docs, the
// left-hand collapsible headings correspond to the section lines in the master watershed
// file (file.cio); this nav follows that exact order and grouping, with each leaf pointing
// at the real input file the SWAT+ Editor edits under that section.
export const SWAT_NAV: NavSection[] = [
  { id: 'home', label: 'Project', icon: 'Home', leaves: [{ label: 'Dashboard', special: 'dashboard' }] },

  { id: 'basin', label: 'Basin', icon: 'Mountain', leaves: [
    { label: 'Codes', file: 'codes.bsn' },
    { label: 'Parameters', file: 'parameters.bsn' },
  ] },

  { id: 'climate', label: 'Climate', icon: 'CloudRain', defaultOpen: true, leaves: [
    { label: 'Weather Stations', file: 'weather-sta.cli' },
    { label: 'Weather Generator', file: 'weather-wgn.cli' },
    { label: 'Precipitation', file: 'pcp.cli' },
    { label: 'Temperature', file: 'tmp.cli' },
  ] },

  { id: 'connect', label: 'Connections', icon: 'Share2', leaves: [
    { label: 'HRUs', file: 'hru.con' },
    { label: 'Routing Units', file: 'rout_unit.con' },
    { label: 'Channels', file: 'chandeg.con' },
    { label: 'Aquifers', file: 'aquifer.con' },
  ] },

  { id: 'channels', label: 'Channels', icon: 'Waves', leaves: [
    { label: 'Initialization', file: 'initial.cha' },
    { label: 'Channel', file: 'channel-lte.cha' },
    { label: 'Hydrology & Sediment', file: 'hyd-sed-lte.cha' },
    { label: 'Nutrients', file: 'nutrients.cha' },
  ] },

  { id: 'routing', label: 'Routing Units', icon: 'Network', leaves: [
    { label: 'Routing Unit', file: 'rout_unit.rtu' },
  ] },

  { id: 'hru', label: 'HRUs', icon: 'Grid3x3', leaves: [
    { label: 'HRU Data', file: 'hru-data.hru' },
  ] },

  { id: 'aquifer', label: 'Aquifers', icon: 'Droplet', leaves: [
    { label: 'Aquifer', file: 'aquifer.aqu' },
    { label: 'Initialization', file: 'initial.aqu' },
  ] },

  { id: 'recall', label: 'Recall / Point Sources', icon: 'Radio', leaves: [
    { label: 'Recall Database', file: 'recall_db.rec' },
  ] },

  { id: 'regions', label: 'Regions', icon: 'Map', leaves: [
    { label: 'Landscape Units', file: 'ls_unit.def' },
    { label: 'Elements', file: 'ls_unit.ele' },
  ] },

  { id: 'hydrology', label: 'Hydrology', icon: 'Droplets', leaves: [
    { label: 'Hydrology', file: 'hydrology.hyd' },
    { label: 'Topography', file: 'topography.hyd' },
    { label: 'Fields', file: 'field.fld' },
  ] },

  { id: 'structural', label: 'Structural', icon: 'Wrench', leaves: [
    { label: 'Tile Drains', file: 'tiledrain.str' },
    { label: 'Septic', file: 'septic.str' },
    { label: 'Filter Strips', file: 'filterstrip.str' },
    { label: 'Grassed Waterways', file: 'grassedww.str' },
    { label: 'User BMPs', file: 'bmpuser.str' },
  ] },

  { id: 'db', label: 'Databases', icon: 'Database', leaves: [
    { label: 'Plants', file: 'plants.plt' },
    { label: 'Fertilizer', file: 'fertilizer.frt' },
    { label: 'Tillage', file: 'tillage.til' },
    { label: 'Pesticides', file: 'pesticide.pes' },
    { label: 'Urban', file: 'urban.urb' },
    { label: 'Septic', file: 'septic.sep' },
    { label: 'Snow', file: 'snow.sno' },
  ] },

  { id: 'ops', label: 'Operations', icon: 'Tractor', leaves: [
    { label: 'Harvest', file: 'harv.ops' },
    { label: 'Graze', file: 'graze.ops' },
    { label: 'Irrigation', file: 'irr.ops' },
    { label: 'Chemical Application', file: 'chem_app.ops' },
    { label: 'Fire', file: 'fire.ops' },
    { label: 'Sweep', file: 'sweep.ops' },
  ] },

  { id: 'lum', label: 'Land Use Management', icon: 'Sprout', leaves: [
    { label: 'Land Use', file: 'landuse.lum' },
    { label: 'Management Schedules', file: 'management.sch' },
    { label: 'Curve Numbers', file: 'cntable.lum' },
    { label: 'Conservation Practices', file: 'cons_practice.lum' },
    { label: "Manning's n", file: 'ovn_table.lum' },
  ] },

  { id: 'dtl', label: 'Decision Tables', icon: 'ListTree', leaves: [
    { label: 'Land Use Management', file: 'lum.dtl' },
    { label: 'Reservoir Release', file: 'res_rel.dtl' },
  ] },

  { id: 'init', label: 'Initialization', icon: 'Leaf', leaves: [
    { label: 'Plant Communities', file: 'plant.ini' },
    { label: 'Soil Plant', file: 'soil_plant.ini' },
    { label: 'Organic Mineral', file: 'om_water.ini' },
  ] },

  { id: 'soils', label: 'Soils', icon: 'Layers', leaves: [
    { label: 'Soils', file: 'soils.sol' },
    { label: 'Nutrients', file: 'nutrients.sol' },
  ] },

  { id: 'change', label: 'Change', icon: 'Sliders', leaves: [
    { label: 'Calibration Parameters', file: 'cal_parms.cal' },
    { label: 'Hard Calibration', file: 'calibration.cal' },
  ] },

  { id: 'run', label: 'Run SWAT+', icon: 'Play', leaves: [
    { label: 'Object Counts', file: 'object.cnt' },
    { label: 'Simulation Time', file: 'time.sim' },
    { label: 'Print Settings', file: 'print.prt' },
    { label: 'Run SWAT+', special: 'run' },
  ] },
];
