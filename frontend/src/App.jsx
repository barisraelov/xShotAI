import { useState } from 'react'
import './index.css'

import Welcome   from './screens/Welcome'
import Dashboard from './screens/Dashboard'
import Upload    from './screens/Upload'
import Analyzing from './screens/Analyzing'
import Session   from './screens/Session'
import Heatmap   from './screens/Heatmap'
import Progress  from './screens/Progress'

// Dev helper: ?demo=session or ?demo=heatmap loads stub result immediately
const DEMO_STUB = {
  job_id: 'demo', status: 'completed',
  summary: { total_shots: 10, made: 6, missed: 4, accuracy_pct: 60.0 },
  shot_points: [
    { shot_id: 's001', result: 'made',   origin: { pixel: { u: 155, v: 430 }, court: { x: 0.08, y: 0.10 } }, zone: { polygon_id: 'three_left_corner',  range_class: 'three_point', label: 'Left corner' } },
    { shot_id: 's002', result: 'missed', origin: { pixel: { u: 870, v: 430 }, court: { x: 0.92, y: 0.10 } }, zone: { polygon_id: 'three_right_corner', range_class: 'three_point', label: 'Right corner' } },
    { shot_id: 's003', result: 'made',   origin: { pixel: { u: 520, v: 380 }, court: { x: 0.50, y: 0.30 } }, zone: { polygon_id: 'mid_center',         range_class: 'mid_range',   label: 'Center' } },
    { shot_id: 's004', result: 'made',   origin: { pixel: { u: 240, v: 355 }, court: { x: 0.19, y: 0.27 } }, zone: { polygon_id: 'mid_left_wing',      range_class: 'mid_range',   label: 'Left wing' } },
    { shot_id: 's005', result: 'missed', origin: { pixel: { u: 800, v: 355 }, court: { x: 0.81, y: 0.27 } }, zone: { polygon_id: 'mid_right_wing',     range_class: 'mid_range',   label: 'Right wing' } },
    { shot_id: 's006', result: 'made',   origin: { pixel: { u: 520, v: 265 }, court: { x: 0.50, y: 0.53 } }, zone: { polygon_id: 'three_top_key',      range_class: 'three_point', label: 'Top of the key' } },
    { shot_id: 's007', result: 'missed', origin: { pixel: { u: 190, v: 300 }, court: { x: 0.14, y: 0.43 } }, zone: { polygon_id: 'three_left_wing',    range_class: 'three_point', label: 'Left wing' } },
    { shot_id: 's008', result: 'made',   origin: { pixel: { u: 845, v: 300 }, court: { x: 0.86, y: 0.43 } }, zone: { polygon_id: 'three_right_wing',   range_class: 'three_point', label: 'Right wing' } },
    { shot_id: 's009', result: 'missed', origin: { pixel: { u: 520, v: 175 }, court: { x: 0.50, y: 0.78 } }, zone: { polygon_id: 'extended',           range_class: 'extended',    label: 'Extended range' } },
    { shot_id: 's010', result: 'made',   origin: { pixel: { u: 460, v: 340 }, court: null }, zone: null },
  ],
  zone_aggregates: [
    { polygon_id: 'three_left_corner',  range_class: 'three_point', label: 'Left corner',     attempts: 1, made: 1, accuracy_pct: 100.0 },
    { polygon_id: 'three_right_corner', range_class: 'three_point', label: 'Right corner',    attempts: 1, made: 0, accuracy_pct: 0.0 },
    { polygon_id: 'mid_center',         range_class: 'mid_range',   label: 'Center',          attempts: 1, made: 1, accuracy_pct: 100.0 },
    { polygon_id: 'mid_left_wing',      range_class: 'mid_range',   label: 'Left wing',       attempts: 1, made: 1, accuracy_pct: 100.0 },
    { polygon_id: 'mid_right_wing',     range_class: 'mid_range',   label: 'Right wing',      attempts: 1, made: 0, accuracy_pct: 0.0 },
    { polygon_id: 'three_top_key',      range_class: 'three_point', label: 'Top of the key',  attempts: 1, made: 1, accuracy_pct: 100.0 },
    { polygon_id: 'three_left_wing',    range_class: 'three_point', label: 'Left wing',       attempts: 1, made: 0, accuracy_pct: 0.0 },
    { polygon_id: 'three_right_wing',   range_class: 'three_point', label: 'Right wing',      attempts: 1, made: 1, accuracy_pct: 100.0 },
    { polygon_id: 'extended',           range_class: 'extended',    label: 'Extended range',  attempts: 1, made: 0, accuracy_pct: 0.0 },
  ],
  mapping: { court_norm_version: '1.0', polygon_version: '1.0', y_flip_applied: false, homography_matrix: null },
}

function demoView() {
  const p = new URLSearchParams(window.location.search).get('demo')
  return p === 'session' || p === 'heatmap' ? p : null
}

const INITIAL_STATE = {
  view:   demoView() ?? 'welcome',
  jobId:  demoView() ? 'demo' : null,
  result: demoView() ? DEMO_STUB : null,
  error:  null,
}

export default function App() {
  const [state, setState] = useState(INITIAL_STATE)

  function navigate(view, patch = {}) {
    setState(s => ({ ...s, view, ...patch }))
  }

  const noNav = state.view === 'welcome' || state.view === 'analyzing'

  const screenProps = {
    navigate,
    jobId:  state.jobId,
    result: state.result,
    error:  state.error,
  }

  return (
    <div className={`app-frame${noNav ? ' no-nav' : ''}`}>
      {state.view === 'welcome'   && <Welcome   {...screenProps} />}
      {state.view === 'dashboard' && <Dashboard {...screenProps} />}
      {state.view === 'upload'    && <Upload    {...screenProps} />}
      {state.view === 'analyzing' && <Analyzing {...screenProps} setState={setState} />}
      {state.view === 'session'   && <Session   {...screenProps} />}
      {state.view === 'heatmap'   && <Heatmap   {...screenProps} />}
      {state.view === 'progress'  && <Progress  {...screenProps} />}
    </div>
  )
}
