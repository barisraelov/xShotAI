import markUrl from '../assets/xshot-mark.svg'

export default function Logo() {
  return (
    <div className="logo" aria-label="xShot AI">
      <img src={markUrl} alt="" className="logo-mark" width={32} height={32} decoding="async" />
      <span className="logo-wordmark">
        <span className="logo-name">xShot</span>
        <span className="logo-suffix">AI</span>
      </span>
    </div>
  )
}
