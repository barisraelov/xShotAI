import { useEffect, useState } from 'react'
import './index.css'

import { isAuthed, setUnauthorizedHandler } from './auth'

import Welcome    from './screens/Welcome'
import Login      from './screens/Login'
import Register   from './screens/Register'
import Dashboard  from './screens/Dashboard'
import Upload     from './screens/Upload'
import Live       from './screens/Live'
import Calibrate  from './screens/Calibrate'
import Analyzing  from './screens/Analyzing'
import Session    from './screens/Session'
import Heatmap    from './screens/Heatmap'
import Progress   from './screens/Progress'
import Statistics from './screens/Statistics'

// Dev helper: ?demo=session or ?demo=heatmap loads stub result immediately
const DEMO_STUB = {
  job_id: 'demo', status: 'completed',
  summary: { total_shots: 10, made: 6, missed: 4, accuracy_pct: 60.0 },
  shot_points: [
    { shot_id: 's001', result: 'made',   origin: { pixel: { u: 155, v: 430 }, court: { x: 0.08, y: 0.10 } }, zone: { polygon_id: 'three_left_corner',  range_class: 'three_point', label: 'Left corner' },     trajectory: { arc_height_px: 86, apex_pixel: { frame_index: 18 }, up_frame: 10, down_frame: 30 } },
    { shot_id: 's002', result: 'missed', origin: { pixel: { u: 870, v: 430 }, court: { x: 0.92, y: 0.10 } }, zone: { polygon_id: 'three_right_corner', range_class: 'three_point', label: 'Right corner' },    trajectory: { arc_height_px: 58, apex_pixel: { frame_index: 14 }, up_frame: 9,  down_frame: 31 } },
    { shot_id: 's003', result: 'made',   origin: { pixel: { u: 520, v: 380 }, court: { x: 0.50, y: 0.30 } }, zone: { polygon_id: 'mid_center',         range_class: 'mid_range',   label: 'Center' },         trajectory: { arc_height_px: 90, apex_pixel: { frame_index: 19 }, up_frame: 11, down_frame: 29 } },
    { shot_id: 's004', result: 'made',   origin: { pixel: { u: 240, v: 355 }, court: { x: 0.19, y: 0.27 } }, zone: { polygon_id: 'mid_left_wing',      range_class: 'mid_range',   label: 'Left wing' },      trajectory: { arc_height_px: 84, apex_pixel: { frame_index: 17 }, up_frame: 10, down_frame: 28 } },
    { shot_id: 's005', result: 'missed', origin: { pixel: { u: 800, v: 355 }, court: { x: 0.81, y: 0.27 } }, zone: { polygon_id: 'mid_right_wing',     range_class: 'mid_range',   label: 'Right wing' },     trajectory: { arc_height_px: 52, apex_pixel: { frame_index: 12 }, up_frame: 8,  down_frame: 30 } },
    { shot_id: 's006', result: 'made',   origin: { pixel: { u: 520, v: 265 }, court: { x: 0.50, y: 0.53 } }, zone: { polygon_id: 'three_top_key',      range_class: 'three_point', label: 'Top of the key' }, trajectory: { arc_height_px: 82, apex_pixel: { frame_index: 18 }, up_frame: 10, down_frame: 30 } },
    { shot_id: 's007', result: 'missed', origin: { pixel: { u: 190, v: 300 }, court: { x: 0.14, y: 0.43 } }, zone: { polygon_id: 'three_left_wing',    range_class: 'three_point', label: 'Left wing' },      trajectory: { arc_height_px: 49, apex_pixel: { frame_index: 11 }, up_frame: 8,  down_frame: 32 } },
    { shot_id: 's008', result: 'made',   origin: { pixel: { u: 845, v: 300 }, court: { x: 0.86, y: 0.43 } }, zone: { polygon_id: 'three_right_wing',   range_class: 'three_point', label: 'Right wing' },     trajectory: { arc_height_px: 79, apex_pixel: { frame_index: 16 }, up_frame: 9,  down_frame: 29 } },
    { shot_id: 's009', result: 'missed', origin: { pixel: { u: 520, v: 175 }, court: { x: 0.50, y: 0.78 } }, zone: { polygon_id: 'extended',           range_class: 'extended',    label: 'Extended range' }, trajectory: { arc_height_px: 47, apex_pixel: { frame_index: 13 }, up_frame: 10, down_frame: 33 } },
    { shot_id: 's010', result: 'made',   origin: { pixel: { u: 460, v: 340 }, court: null }, zone: null, trajectory: { arc_height_px: 74, apex_pixel: { frame_index: 15 }, up_frame: 9, down_frame: 28 } },
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
  feedback: {
    summary: {
      headline: '6/10 makes (60%)',
      body: 'Session summary: 6 made, 4 missed over 10 detected attempts.',
    },
    insights: [
      'Session accuracy at 60% — room to push into the next tier.',
      'More misses than makes (4 vs 6).',
      'Arc height varied noticeably between attempts — aim for a more consistent release arc.',
      'Shot timing was inconsistent — the apex arrived at different points in the up-to-down window across attempts.',
    ],
    recommendations: [
      'Focus on repeatable footwork and release timing between attempts.',
      'Repeat form shots aiming for the same target arc on each release.',
      'Slow the motion slightly and keep a repeatable release rhythm from shot to shot.',
    ],
    metrics: {
      sample_shots: 10, reported_made: 6, reported_missed: 4,
      reported_accuracy_pct: 60.0, longest_make_streak: 2, longest_miss_streak: 1,
      ending_streak_type: 'made', ending_streak_length: 1,
      trajectory_shots_with_arc_height: 10, trajectory_mean_arc_height_px: 70.1,
      trajectory_mean_arc_height_made_px: 82.5, trajectory_mean_arc_height_missed_px: 51.5,
      first_half_mean_arc_height_px: 74.0, second_half_mean_arc_height_px: 66.2,
      arc_height_delta_px: -7.8, apex_timing_mean: 0.34, apex_timing_spread: 0.28,
    },
  },
}

function demoView() {
  const p = new URLSearchParams(window.location.search).get('demo')
  return p === 'session' || p === 'heatmap' ? p : null
}

const INITIAL_STATE = {
  view:   demoView() ?? (isAuthed() ? 'dashboard' : 'welcome'),
  jobId:  demoView() ? 'demo' : null,
  result: demoView() ? DEMO_STUB : null,
  error:  null,
  file:   null,   // holds the video File object during the upload→calibrate→analyzing flow
  liveDiagnostics: null,
}

const NO_NAV_VIEWS = new Set(['welcome', 'login', 'register', 'analyzing', 'calibrate', 'live'])

export default function App() {
  const [state, setState] = useState(INITIAL_STATE)

  function navigate(view, patch = {}) {
    setState(s => ({ ...s, view, ...patch }))
  }

  // Any authenticated request that comes back 401 (expired/invalid token) sends
  // the user to the login screen.
  useEffect(() => {
    setUnauthorizedHandler(() => setState(s => ({ ...s, view: 'login', error: null })))
    return () => setUnauthorizedHandler(null)
  }, [])

  const noNav = NO_NAV_VIEWS.has(state.view)

  const screenProps = {
    navigate,
    jobId:  state.jobId,
    result: state.result,
    error:  state.error,
    file:   state.file,
    liveDiagnostics: state.liveDiagnostics,
  }

  return (
    <div className={`app-frame${noNav ? ' no-nav' : ''}${state.view === 'live' ? ' live-mode' : ''}`}>
      {state.view === 'welcome'    && <Welcome    {...screenProps} />}
      {state.view === 'login'      && <Login      {...screenProps} />}
      {state.view === 'register'   && <Register   {...screenProps} />}
      {state.view === 'dashboard'  && <Dashboard  {...screenProps} />}
      {state.view === 'upload'     && <Upload     {...screenProps} />}
      {state.view === 'live'       && <Live       {...screenProps} />}
      {state.view === 'calibrate'  && <Calibrate  {...screenProps} />}
      {state.view === 'analyzing'  && <Analyzing  {...screenProps} setState={setState} />}
      {state.view === 'session'    && <Session    {...screenProps} />}
      {state.view === 'heatmap'    && <Heatmap    {...screenProps} />}
      {state.view === 'progress'   && <Progress   {...screenProps} />}
      {state.view === 'statistics' && <Statistics {...screenProps} />}
    </div>
  )
}
