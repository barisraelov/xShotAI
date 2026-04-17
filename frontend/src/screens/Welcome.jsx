import Logo from '../components/Logo'
import './Welcome.css'

export default function Welcome({ navigate }) {
  return (
    <div className="screen-enter welcome">
      <div className="top-bar">
        <Logo />
      </div>

      <div className="welcome-hero">
        <h1>Analyze your basketball shot<br /><span className="accent">using AI</span></h1>
      </div>

      <ul className="steps">
        <li>
          <div className="step-icon">▶</div>
          <div><strong>Upload video</strong><span>Record or pick from gallery</span></div>
        </li>
        <li>
          <div className="step-icon">🧠</div>
          <div><strong>AI analysis</strong><span>Detects shots and makes / misses</span></div>
        </li>
        <li>
          <div className="step-icon">📊</div>
          <div><strong>Performance insights</strong><span>Stats and shot map by zone</span></div>
        </li>
      </ul>

      <div className="cta-row">
        <button className="btn" onClick={() => navigate('dashboard')}>Log In</button>
        <button className="btn btn-primary" onClick={() => navigate('dashboard')}>Sign Up</button>
      </div>

      <p className="slogan">Track · Improve · <b>Dominate</b></p>
    </div>
  )
}
