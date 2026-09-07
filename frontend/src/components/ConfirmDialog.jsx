import { useEffect, useRef } from 'react'
import './ConfirmDialog.css'

/**
 * Small modal confirm. Renders nothing when `open` is false.
 *
 * Props:
 *   open        – show/hide
 *   title       – heading text
 *   message     – body text
 *   confirmLabel / cancelLabel – button text (defaults "Delete" / "Cancel")
 *   danger      – style the confirm button as destructive (default true)
 *   busy        – disable both buttons, show a spinner on confirm
 *   onCancel / onConfirm – handlers
 *
 * Escape and a backdrop click both cancel (ignored while `busy`).
 */
export default function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = 'Delete',
  cancelLabel = 'Cancel',
  danger = true,
  busy = false,
  onCancel,
  onConfirm,
}) {
  const cancelRef = useRef(null)

  useEffect(() => {
    if (!open) return undefined
    cancelRef.current?.focus()
    function onKey(e) {
      if (e.key === 'Escape' && !busy) onCancel?.()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, busy, onCancel])

  if (!open) return null

  return (
    <div
      className="confirm-backdrop"
      onClick={() => { if (!busy) onCancel?.() }}
    >
      <div
        className="confirm-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        onClick={e => e.stopPropagation()}
      >
        <h3 className="confirm-title" id="confirm-title">{title}</h3>
        <p className="confirm-message">{message}</p>
        <div className="confirm-actions">
          <button
            type="button"
            className="confirm-btn confirm-btn--ghost"
            onClick={onCancel}
            disabled={busy}
            ref={cancelRef}
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            className={`confirm-btn ${danger ? 'confirm-btn--danger' : 'confirm-btn--primary'}`}
            onClick={onConfirm}
            disabled={busy}
          >
            {busy ? <span className="confirm-spinner" aria-hidden="true" /> : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
