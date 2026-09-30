import { useState } from 'react'
import { Link } from 'react-router-dom'
import { motion } from 'framer-motion'
import { Mail, Lock, Eye, EyeOff, Info } from 'lucide-react'

export function LoginPage() {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)

  return (
    <div className="auth-page">
      <div className="auth-glow" aria-hidden="true" />
      <motion.div
        className="auth-container"
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: [0.2, 0.7, 0.3, 1] }}
      >
        <div className="auth-header">
          <Link to="/" className="auth-logo" aria-label="Live Fact-Checker home">
            <span className="auth-logo-mark" aria-hidden="true" />
            <span>LIVE FACT-CHECKER</span>
          </Link>
        </div>

        <motion.div
          className="auth-card"
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, delay: 0.1, ease: [0.2, 0.7, 0.3, 1] }}
        >
          <div className="auth-title-group">
            <h1 className="auth-title">Sign in</h1>
            <p className="auth-subtitle">Account access is not available yet.</p>
          </div>

          <div className="auth-notice" role="status">
            <Info size={18} aria-hidden="true" />
            <div>
              <strong>Accounts are not implemented.</strong>
              <p>
                There is no authentication service behind this form, so nothing is submitted
                and no credentials are stored. The fact-checker itself is open right now.
              </p>
            </div>
          </div>

          <form className="auth-form" onSubmit={(event) => event.preventDefault()} noValidate>
            <div className="auth-field">
              <label htmlFor="login-email" className="auth-label">
                Email
              </label>
              <div className="auth-input-wrapper">
                <Mail className="auth-input-icon" size={18} aria-hidden="true" />
                <input
                  type="email"
                  id="login-email"
                  name="email"
                  className="auth-input"
                  placeholder="you@example.com"
                  autoComplete="email"
                  value={email}
                  onChange={(event) => setEmail(event.target.value)}
                  disabled
                />
              </div>
            </div>

            <div className="auth-field">
              <label htmlFor="login-password" className="auth-label">
                Password
              </label>
              <div className="auth-input-wrapper">
                <Lock className="auth-input-icon" size={18} aria-hidden="true" />
                <input
                  type={showPassword ? 'text' : 'password'}
                  id="login-password"
                  name="password"
                  className="auth-input"
                  placeholder="••••••••"
                  autoComplete="current-password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  disabled
                />
                <button
                  type="button"
                  className="auth-password-toggle"
                  onClick={() => setShowPassword((current) => !current)}
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                  disabled
                >
                  {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                </button>
              </div>
            </div>

            <button type="submit" className="button button--primary button--lg button--full" disabled>
              Sign in
            </button>
          </form>

          <Link to="/dashboard" className="button button--secondary button--lg button--full auth-alt">
            Open the fact-checker instead
          </Link>

          <p className="auth-footer">
            Don&apos;t have an account? <Link to="/signup" className="auth-link">Sign up</Link>
          </p>
        </motion.div>
      </motion.div>
    </div>
  )
}
