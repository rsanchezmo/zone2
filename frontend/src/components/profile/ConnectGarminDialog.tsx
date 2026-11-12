import { useState, type FormEvent } from 'react'
import { errorDetail } from '../../api/client'
import { useGarminSignIn, useGarminSignInCode } from '../../api/garmin'
import { useToast } from '../../hooks/useToast'
import HaloButton from '../shared/HaloButton'
import Modal from '../shared/Modal'

const GARMIN_CYAN = '#06b6d4'

/** Signs in to Garmin Connect: the email and password, then the code Garmin sends when it asks for one. */
export default function ConnectGarminDialog({ onClose }: { onClose: () => void }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const signIn = useGarminSignIn()
  const enterCode = useGarminSignInCode()
  const { toast } = useToast()
  const needsCode = signIn.data?.needs_code === true
  const pending = signIn.isPending || enterCode.isPending
  const failure = needsCode ? enterCode.error : signIn.error

  const connected = () => {
    toast('Garmin connected: syncing the last 14 days', 'success')
    onClose()
  }
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (needsCode) enterCode.mutate(code, { onSuccess: connected })
    else signIn.mutate({ email, password }, { onSuccess: data => { if (!data.needs_code) connected() } })
  }
  const startAgain = () => {
    signIn.reset()
    enterCode.reset()
    setCode('')
  }

  return (
    <Modal onClose={onClose} className="p-6 max-w-sm">
      <form onSubmit={submit} className="space-y-4">
        <div className="space-y-1">
          <div className="text-sm font-medium text-fg">Connect Garmin</div>
          <p className="text-xs text-gray-500 leading-relaxed">
            z2 signs in to Garmin Connect once and keeps the session, never your password.
          </p>
        </div>

        {needsCode ? (
          <label className="block space-y-1.5">
            <span className="text-xs text-gray-500">Enter the code Garmin sent you</span>
            <input className="input w-full tracking-[0.3em] font-mono" inputMode="numeric" autoComplete="one-time-code"
              autoFocus value={code} onChange={e => setCode(e.target.value)} />
          </label>
        ) : (
          <div className="space-y-2">
            <input className="input w-full" type="email" autoComplete="username" placeholder="Garmin email" autoFocus
              value={email} onChange={e => setEmail(e.target.value)} />
            <input className="input w-full" type="password" autoComplete="current-password" placeholder="Password"
              value={password} onChange={e => setPassword(e.target.value)} />
          </div>
        )}

        {failure && <div className="text-xs text-red-400">{errorDetail(failure, 'Garmin sign-in failed')}</div>}
        {signIn.isPending && <div className="text-[11px] text-gray-500">Garmin can take a few seconds…</div>}

        <div className="flex items-center justify-between gap-3">
          <button type="button" className="text-xs text-gray-500 hover:text-fg transition-colors" disabled={pending}
            onClick={needsCode ? startAgain : onClose}>
            {needsCode ? 'Start again' : 'Cancel'}
          </button>
          <HaloButton type="submit" color={GARMIN_CYAN} disabled={pending || (needsCode ? !code : !email || !password)}>
            {pending ? 'Signing in…' : needsCode ? 'Verify code' : 'Connect'}
          </HaloButton>
        </div>
      </form>
    </Modal>
  )
}
